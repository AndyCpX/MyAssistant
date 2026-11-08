"""Servizio eventi/notifiche di JARVIS.

Chi lo usa:
- CI, Home Assistant, script: POST /v1/events (per notifiche e timer programmati);
- agente: GET /v1/pending e POST /v1/notifications/{id}/ack, per conto delle schede;
- operatore: GET /v1/notifications, DELETE /v1/notifications/{id}.

Tutte le rotte /v1 richiedono `Authorization: Bearer NOTIFY_TOKEN`.
La scheda ESP32 non parla mai con questo servizio: passa dall'agente.
"""
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from .store import TARGET_RE, Store, utcnow

log = logging.getLogger("notify")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

store: Store


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store
    if not os.getenv("NOTIFY_TOKEN", ""):
        # Senza token il servizio non deve partire: sarebbe aperto a chiunque sulla rete.
        raise RuntimeError("NOTIFY_TOKEN non impostato")
    store = Store(os.getenv("NOTIFY_DB", "/data/notify.db"))
    yield
    store.close()


app = FastAPI(title="JARVIS notify", lifespan=lifespan)


def check_auth(req: Request) -> None:
    token = os.getenv("NOTIFY_TOKEN", "")
    if not token or not hmac.compare_digest(req.headers.get("authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "token non valido")


class EventIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    # "all" = tutti i dispositivi; "device:<id>" = una scheda; "person:<nome>" = chi viene riconosciuto
    target: str = "all"
    priority: Literal["normal", "high"] = "normal"
    # Con timezone obbligatorio: niente ambiguita' sull'ora locale. Assente = subito.
    deliver_at: datetime | None = None
    expires_at: datetime | None = None
    source: str = Field(default="unknown", min_length=1, max_length=64)
    # Chiave per evitare doppioni (es. retry della CI): stessa (source, dedupe_key) = stessa notifica.
    dedupe_key: str | None = Field(default=None, max_length=128)

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("testo vuoto")
        return v

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        v = v.strip().lower()
        if not TARGET_RE.match(v):
            raise ValueError("target non valido: usa all, device:<id> o person:<nome>")
        return v

    @field_validator("deliver_at", "expires_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("serve un orario con fuso (es. 2026-11-08T18:00:00+01:00)")
        return v


@app.get("/healthz", status_code=204)
def healthz() -> Response:
    return Response(status_code=204)


@app.post("/v1/events", status_code=201, dependencies=[Depends(check_auth)])
def create_event(body: EventIn) -> dict:
    now = utcnow()
    deliver_at = body.deliver_at or now
    if body.expires_at and body.expires_at <= deliver_at:
        raise HTTPException(422, "expires_at deve essere dopo deliver_at")
    nid, created = store.add(
        text=body.text, target=body.target, priority=body.priority, source=body.source,
        deliver_at=deliver_at, expires_at=body.expires_at, dedupe_key=body.dedupe_key,
    )
    log.info("evento %s da %s -> %s (%s)", nid, body.source, body.target,
             "nuovo" if created else "duplicato")
    return {"id": nid, "status": "created" if created else "duplicate"}


@app.get("/v1/pending", dependencies=[Depends(check_auth)])
def pending(device: str = Query(min_length=1, max_length=64),
            speaker: str | None = Query(default=None, max_length=64)) -> dict:
    """Una notifica alla volta, con lease. La scheda la riproduce e poi chiama l'ack."""
    return {"notification": store.next_for(device, speaker)}


@app.post("/v1/notifications/{nid}/ack", status_code=204, dependencies=[Depends(check_auth)])
def ack(nid: str, device: str = Query(min_length=1, max_length=64)) -> Response:
    if not store.ack(nid, device):
        raise HTTPException(404, "notifica sconosciuta")
    return Response(status_code=204)


@app.get("/v1/notifications", dependencies=[Depends(check_auth)])
def list_notifications(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return {"items": store.list(limit)}


@app.delete("/v1/notifications/{nid}", status_code=204, dependencies=[Depends(check_auth)])
def cancel(nid: str) -> Response:
    if not store.cancel(nid):
        raise HTTPException(404, "notifica sconosciuta")
    return Response(status_code=204)
