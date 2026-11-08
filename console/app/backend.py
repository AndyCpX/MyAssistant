"""Client verso i servizi esistenti. La console non legge Qdrant ne' i file dei dati direttamente:
passa dalle API dell'agente (che possiede memorie e voci) e del servizio notify."""
import asyncio
import os
from typing import Any

import httpx


class ServiceError(RuntimeError):
    def __init__(self, service: str, detail: str) -> None:
        super().__init__(f"{service}: {detail}")
        self.service = service


def _agent_base() -> str:
    return os.getenv("AGENT_URL", "http://agent:8080").rstrip("/")


def _notify_base() -> str:
    return os.getenv("NOTIFY_URL", "http://notify:8080").rstrip("/")


async def _call(service: str, base: str, token: str, method: str, path: str,
                params: dict | None = None, content: bytes | None = None,
                headers: dict | None = None) -> Any:
    h = {"Authorization": f"Bearer {token}"} if token else {}
    h |= headers or {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.request(method, f"{base}{path}", params=params, content=content, headers=h)
    except httpx.HTTPError as e:
        raise ServiceError(service, f"non raggiungibile ({type(e).__name__})")
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise ServiceError(service, f"HTTP {r.status_code}")
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


async def agent(method: str, path: str, **kw) -> Any:
    return await _call("agente", _agent_base(), os.getenv("AGENT_TOKEN", ""), method, path, **kw)


async def notify(method: str, path: str, **kw) -> Any:
    return await _call("notify", _notify_base(), os.getenv("NOTIFY_TOKEN", ""), method, path, **kw)


async def health() -> dict:
    async def probe(base: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{base}/healthz")
            return "ok" if r.status_code < 400 else f"HTTP {r.status_code}"
        except httpx.HTTPError:
            return "non raggiungibile"
    agent_s, notify_s = await asyncio.gather(probe(_agent_base()), probe(_notify_base()))
    return {"agent": agent_s, "notify": notify_s}
