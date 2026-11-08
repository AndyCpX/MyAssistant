"""Client del servizio eventi (notify/). Se NOTIFY_URL non e' impostato, tutto resta disattivato."""
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("notify")


def enabled() -> bool:
    return bool(os.getenv("NOTIFY_URL", "").strip())


def person_target(name: str) -> str:
    """Stesso nome, stessa chiave: creazione e lettura devono normalizzare allo stesso modo."""
    return "person:" + re.sub(r"[^\w.-]", "_", name.strip()).lower()


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('NOTIFY_TOKEN', '')}"}


def _base() -> str:
    return os.getenv("NOTIFY_URL", "").rstrip("/")


async def create(text: str, target: str, *, minutes_from_now: int = 0, source: str = "agent") -> str:
    """Programma una notifica. Restituisce l'id (o solleva eccezione)."""
    when = datetime.now(timezone.utc) + timedelta(minutes=max(0, minutes_from_now))
    body = {"text": text, "target": target, "source": source,
            "deliver_at": when.isoformat(timespec="seconds")}
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(f"{_base()}/v1/events", json=body, headers=_headers())
        r.raise_for_status()
        return r.json()["id"]


async def pending(device: str, speaker: str | None = None) -> dict | None:
    params = {"device": device}
    if speaker:
        params["speaker"] = person_target(speaker).removeprefix("person:")
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{_base()}/v1/pending", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()["notification"]


async def ack(nid: str, device: str) -> None:
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(f"{_base()}/v1/notifications/{nid}/ack", params={"device": device},
                         headers=_headers())
        r.raise_for_status()
