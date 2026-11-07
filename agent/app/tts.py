"""Sintesi vocale ElevenLabs: PCM 16 kHz mono in streaming."""
import logging
import os
import re
import secrets
import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator

import httpx

log = logging.getLogger("tts")

TTL_S = 120
MAX_PENDING = 16
_pending: OrderedDict[str, tuple["asyncio.Task[bytes]", float]] = OrderedDict()
MAX_CHARS = 240   # ~16 s di voce: oltre, l'ESP32 aspetterebbe troppo e risponde un monologo

def speech_text(text: str, limit: int = MAX_CHARS) -> str:
    """Toglie markdown/elenchi e tronca a fine frase: il testo viene letto ad alta voce."""
    t = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    t = re.sub(r"[*_#`>]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    k = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("; "))
    return cut[: k + 1] if k > 60 else cut.rsplit(" ", 1)[0] + "."

def enabled() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY") and os.getenv("ELEVENLABS_VOICE_ID"))

async def _synth(text: str) -> bytes:
    t0 = time.monotonic()
    pcm = b"".join([c async for c in stream_pcm(text)])
    log.info("TEMPI tts=%.1fs (%d byte, %d ms di audio)", time.monotonic() - t0, len(pcm), len(pcm) // 32)
    return pcm

def register(text: str) -> str:
    """Avvia subito la sintesi in background; l'ESP32 scarichera' il risultato con GET /v1/reply/<id>."""
    now = time.monotonic()
    for k in [k for k, (_, t) in _pending.items() if now - t > TTL_S]:
        _pending.pop(k)[0].cancel()
    while len(_pending) >= MAX_PENDING:
        _pending.popitem(last=False)[1][0].cancel()
    rid = secrets.token_urlsafe(9)
    _pending[rid] = (asyncio.create_task(_synth(text)), now)
    return rid

async def fetch(rid: str) -> bytes | None:
    item = _pending.get(rid)
    return await item[0] if item else None

async def stream_pcm(text: str) -> AsyncIterator[bytes]:
    """Inoltra l'audio PCM16 mono 16 kHz man mano che ElevenLabs lo genera (chunk sempre di lunghezza pari)."""
    voice = os.environ["ELEVENLABS_VOICE_ID"]
    body = {"text": text, "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")}
    if lang := os.getenv("ELEVENLABS_LANGUAGE"):
        body["language_code"] = lang
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
    carry = b""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
        async with client.stream(
            "POST", url, params={"output_format": "pcm_16000"}, json=body,
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        ) as r:
            if r.status_code != 200:
                log.error("ElevenLabs HTTP %d: %s", r.status_code, (await r.aread())[:300])
                return
            async for chunk in r.aiter_bytes():
                data = carry + chunk
                n = len(data) // 2 * 2
                carry = data[n:]
                if n:
                    yield data[:n]
