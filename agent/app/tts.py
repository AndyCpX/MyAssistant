"""Sintesi vocale: Kokoro locale (default) con ripiego su ElevenLabs, o viceversa (TTS_ENGINE). Uscita PCM 16 kHz mono."""
import asyncio
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator

import httpx
import numpy as np

log = logging.getLogger("tts")

TTL_S = 120
MAX_PENDING = 16
_pending: OrderedDict[str, tuple["asyncio.Task[bytes]", float]] = OrderedDict()
MAX_CHARS = 240   # ~16 s di voce: oltre, l'ESP32 aspetterebbe troppo e risponde un monologo

KOKORO_RATE = 24000   # frequenza nativa di Kokoro; l'ESP32 vuole 16 kHz
_kokoro = None
_kokoro_lock = threading.Lock()


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


# --- Disponibilita' dei motori ---

def _kokoro_paths() -> tuple[str, str]:
    return (os.getenv("KOKORO_MODEL", "/models/kokoro/kokoro-v1.0.onnx"),
            os.getenv("KOKORO_VOICES", "/models/kokoro/voices-v1.0.bin"))


def _kokoro_ok() -> bool:
    return all(os.path.isfile(p) for p in _kokoro_paths())


def _eleven_ok() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY") and os.getenv("ELEVENLABS_VOICE_ID"))


def _engines() -> list[str]:
    """Motori usabili, nell'ordine di preferenza (il primo e' quello di TTS_ENGINE, l'altro e' il ripiego)."""
    order = ["kokoro", "elevenlabs"]
    if os.getenv("TTS_ENGINE", "kokoro").strip().lower() == "elevenlabs":
        order.reverse()
    ok = {"kokoro": _kokoro_ok, "elevenlabs": _eleven_ok}
    return [e for e in order if ok[e]()]


def enabled() -> bool:
    return bool(_engines())


# --- Kokoro (locale, ONNX su CPU) ---

def _load_kokoro():
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro   # import tardivo: l'agente parte anche senza il pacchetto
            model, voices = _kokoro_paths()
            log.info("carico modello TTS Kokoro %s", model)
            _kokoro = Kokoro(model, voices)
        return _kokoro


def warmup() -> None:
    """Carica Kokoro all'avvio (se usato) per non pagare 1-2 s sulla prima risposta."""
    if "kokoro" in _engines():
        try:
            _load_kokoro()
        except Exception:
            log.exception("Kokoro non caricabile: si usera' il ripiego")


def _kokoro_pcm(text: str) -> bytes:
    """Testo -> PCM16 16 kHz mono (bloccante: va chiamata in un thread)."""
    from scipy.signal import resample_poly
    samples, rate = _load_kokoro().create(
        text,
        voice=os.getenv("KOKORO_VOICE", "if_sara"),
        speed=float(os.getenv("KOKORO_SPEED", "1.0")),
        lang=os.getenv("KOKORO_LANG", "it"),
    )
    if rate != 16000:
        g = np.gcd(int(rate), 16000)
        samples = resample_poly(samples, 16000 // g, int(rate) // g)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


async def _kokoro_stream(text: str) -> AsyncIterator[bytes]:
    pcm = await asyncio.to_thread(_kokoro_pcm, text)
    if pcm:
        yield pcm


# --- ElevenLabs ---

async def _eleven_stream(text: str) -> AsyncIterator[bytes]:
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


_STREAMS = {"kokoro": _kokoro_stream, "elevenlabs": _eleven_stream}


async def stream_pcm(text: str) -> AsyncIterator[bytes]:
    """PCM16 16 kHz mono dal primo motore che produce audio; se fallisce senza emettere nulla passa al successivo."""
    for engine in _engines():
        started = False
        try:
            async for chunk in _STREAMS[engine](text):
                started = True
                yield chunk
        except Exception:
            log.exception("TTS %s fallito", engine)
        if started:
            return
        log.warning("TTS %s non ha prodotto audio: provo il ripiego", engine)


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
