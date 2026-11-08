"""Servizio eventi/notifiche di JARVIS.

Chi lo usa:
- sorgenti (CI, Home Assistant): POST /v1/events con il proprio token (NOTIFY_SOURCE_TOKENS);
- agente (NOTIFY_TOKEN): GET /v1/pending e ack per i promemoria personali, GET /v1/notifications/{id}
  per dare alla scheda il testo da pronunciare;
- schede: ricevono gli id su MQTT (jarvis/notify/<id>) e confermano su jarvis/ack/<id>; non parlano mai
  direttamente con questo servizio;
- operatore: GET /v1/notifications, DELETE /v1/notifications/{id}.
"""
import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import mqtt_link
from .store import TARGET_RE, Store, utcnow

log = logging.getLogger("notify")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

store: Store
_link: mqtt_link.Link | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store, _link
    if not os.getenv("NOTIFY_TOKEN", ""):
        # Senza token il servizio non deve partire: sarebbe aperto a chiunque sulla rete.
        raise RuntimeError("NOTIFY_TOKEN non impostato")
    store = Store(os.getenv("NOTIFY_DB", "/data/notify.db"))
    task = None
    _link = mqtt_link.from_env(store)
    if _link:
        _link.start()
        task = asyncio.create_task(_link.run())
        log.info("MQTT attivo, dispositivi: %s", ", ".join(_link.devices) or "(nessuno)")
    yield
    if task:
        task.cancel()
    if _link:
        _link.stop()
    store.close()


app = FastAPI(title="JARVIS notify", lifespan=lifespan)


def check_auth(req: Request) -> None:
    """Token dell'agente: accesso completo."""
    token = os.getenv("NOTIFY_TOKEN", "")
    if not token or not hmac.compare_digest(req.headers.get("authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "token non valido")


def _source_tokens() -> dict[str, str]:
    """NOTIFY_SOURCE_TOKENS="ci=<token>,ha=<token>": ogni sorgente ha il suo token."""
    out: dict[str, str] = {}
    for pair in os.getenv("NOTIFY_SOURCE_TOKENS", "").split(","):
        if "=" in pair:
            name, tok = pair.split("=", 1)
            if name.strip() and tok.strip():
                out[tok.strip()] = name.strip()
    return out


def event_source(req: Request) -> str | None:
    """Chi sta inviando un evento: nome della sorgente (token dedicato) oppure "agent"."""
    header = req.headers.get("authorization", "")
    if os.getenv("NOTIFY_TOKEN", "") and hmac.compare_digest(header, f"Bearer {os.getenv('NOTIFY_TOKEN')}"):
        return "agent"
    for tok, name in _source_tokens().items():
        if hmac.compare_digest(header, f"Bearer {tok}"):
            return name
    return None


class RateLimiter:
    """Finestra fissa di un minuto per sorgente: un token rubato non puo' inondare la scheda."""

    def __init__(self, per_minute: int) -> None:
        self.limit = per_minute
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, source: str) -> bool:
        now = time.monotonic()
        start, count = self._hits.get(source, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        if count >= self.limit:
            return False
        self._hits[source] = (start, count + 1)
        return True


limiter = RateLimiter(int(os.getenv("NOTIFY_RATE_PER_MIN", "30")))


class EventIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    # "all" = tutti i dispositivi configurati; "device:<id>" = una scheda; "person:<nome>" = chi viene riconosciuto
    target: str = "all"
    priority: Literal["normal", "high"] = "normal"
    # Con timezone obbligatorio: niente ambiguita' sull'ora locale. Assente = subito.
    deliver_at: datetime | None = None
    expires_at: datetime | None = None
    # Ignorato per i token di sorgente: vale il nome associato al token.
    source: str = Field(default="agent", min_length=1, max_length=64)
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


@app.post("/v1/events", status_code=201)
def create_event(req: Request, body: EventIn) -> dict:
    source = event_source(req)
    if source is None:
        raise HTTPException(401, "token non valido")
    if not limiter.allow(source):
        raise HTTPException(429, "troppi eventi da questa sorgente")
    now = utcnow()
    deliver_at = body.deliver_at or now
    if body.expires_at and body.expires_at <= deliver_at:
        raise HTTPException(422, "expires_at deve essere dopo deliver_at")
    nid, created = store.add(
        text=body.text, target=body.target, priority=body.priority, source=source,
        deliver_at=deliver_at, expires_at=body.expires_at, dedupe_key=body.dedupe_key,
    )
    log.info("evento %s da %s -> %s (%s)", nid, source, body.target,
             "nuovo" if created else "duplicato")
    return {"id": nid, "status": "created" if created else "duplicate"}


@app.get("/v1/pending", dependencies=[Depends(check_auth)])
def pending(device: str = Query(min_length=1, max_length=64),
            speaker: str = Query(min_length=1, max_length=64)) -> dict:
    """Promemoria della persona riconosciuta, con lease. La scheda/agente conferma con l'ack."""
    return {"notification": store.person_next(device, speaker)}


@app.get("/v1/notifications/{nid}", dependencies=[Depends(check_auth)])
def get_notification(nid: str) -> dict:
    n = store.get(nid)
    if n is None or n["cancelled"]:
        raise HTTPException(404, "notifica sconosciuta")
    return n


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
