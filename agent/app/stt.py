"""Trascrizione locale con faster-whisper."""
import io
import logging
import os
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger("stt")
_model: WhisperModel | None = None
_lock = threading.Lock()


def load() -> WhisperModel:
    global _model
    with _lock:
        if _model is None:
            name = os.getenv("STT_MODEL", "small")
            log.info("carico modello STT %s", name)
            _model = WhisperModel(name, device="cpu", compute_type=os.getenv("STT_COMPUTE_TYPE", "int8"))
        return _model


def _local(pcm16le: bytes, rate: int) -> str:
    """PCM16 little-endian mono -> testo con faster-whisper locale. Il modello vuole 16 kHz."""
    pcm = np.frombuffer(pcm16le[: len(pcm16le) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    if rate != 16000:
        n = int(len(pcm) * 16000 / rate)
        pcm = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)
    segments, _ = load().transcribe(
        pcm,
        language=os.getenv("STT_LANGUAGE", "it") or None,
        initial_prompt=os.getenv("STT_PROMPT", "Jarvis.") or None,   # nomi propri attesi, es. "Jarvis, Andrea, Marta."
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


_http = httpx.Client(timeout=httpx.Timeout(20, connect=5))   # connessione riutilizzata: niente handshake TLS a ogni frase


def _wav(pcm16le: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16le[: len(pcm16le) // 2 * 2])
    return buf.getvalue()


def _elevenlabs(pcm16le: bytes, rate: int) -> str:
    """Scribe di ElevenLabs (stessa chiave del TTS)."""
    data = {"model_id": os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1"), "tag_audio_events": "false"}
    if lang := os.getenv("STT_LANGUAGE", "it"):
        data["language_code"] = lang
    r = _http.post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        data=data,
        files={"file": ("audio.wav", _wav(pcm16le, rate), "audio/wav")},
    )
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


_ENGINES = {"local": _local, "elevenlabs": _elevenlabs}
_bg = ThreadPoolExecutor(max_workers=1)


def _run(name: str, pcm: bytes, rate: int) -> tuple[str, float]:
    t0 = time.monotonic()
    return _ENGINES[name](pcm, rate), time.monotonic() - t0


def transcribe(pcm16le: bytes, rate: int) -> str:
    """Motore scelto con STT_ENGINE (local|elevenlabs); se fallisce si ripiega sul locale.
    Con STT_COMPARE=1 l'altro motore gira in parallelo e i due risultati finiscono nel log (solo diagnostica)."""
    primary = os.getenv("STT_ENGINE", "local")
    if primary not in _ENGINES:
        primary = "local"
    other = "local" if primary == "elevenlabs" else "elevenlabs"
    if os.getenv("STT_COMPARE") == "1" and os.getenv("ELEVENLABS_API_KEY"):
        def side() -> None:
            try:
                txt, dt = _run(other, pcm16le, rate)
                log.info("CONFRONTO %s (%.1fs): %r", other, dt, txt)
            except Exception as e:
                log.warning("CONFRONTO %s fallito: %s", other, e)
        _bg.submit(side)
    try:
        txt, dt = _run(primary, pcm16le, rate)
        log.info("STT %s (%.1fs): %r", primary, dt, txt)
        return txt
    except Exception as e:
        if primary == "local":
            raise
        log.warning("STT %s fallito (%s): ripiego sul locale", primary, e)
        return _run("local", pcm16le, rate)[0]
