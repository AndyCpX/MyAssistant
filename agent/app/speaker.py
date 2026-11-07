"""Riconoscimento del parlante (speaker embedding con sherpa-onnx, tutto locale).

I vettori vocali sono dati biometrici: restano nel volume /data, mai inviati a servizi esterni.
"""
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx

log = logging.getLogger("speaker")

MODEL = os.getenv("SPEAKER_MODEL", "/models/speaker.onnx")
STORE = Path(os.getenv("SPEAKER_STORE", "/data/speakers.json"))
THRESHOLD = float(os.getenv("SPEAKER_THRESHOLD", "0.65"))   # similarità coseno minima
MIN_SECONDS = 1.0                                            # sotto questa durata non si identifica

_extractor = None
_lock = threading.Lock()
_speakers: dict[str, dict] = {}


@dataclass
class Match:
    name: str | None   # None = sconosciuto / ospite
    score: float       # similarità col miglior candidato (0 se nessuno registrato)
    role: str = "guest"
    margin: float = 0.0   # distacco dal secondo candidato (1.0 se e' l'unica persona registrata)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def enabled() -> bool:
    return os.path.exists(MODEL)


def load() -> None:
    global _extractor
    with _lock:
        if _extractor is None:
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=2, provider="cpu")
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            if STORE.exists():
                _speakers.update(json.loads(STORE.read_text(encoding="utf-8")))
            log.info("riconoscimento parlante pronto (%d persone registrate)", len(_speakers))


def embed(pcm16le: bytes, rate: int) -> np.ndarray:
    """PCM16 mono -> embedding normalizzato."""
    load()
    x = np.frombuffer(pcm16le[: len(pcm16le) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    with _lock:
        stream = _extractor.create_stream()
        stream.accept_waveform(sample_rate=rate, waveform=x)
        stream.input_finished()
        return _unit(np.array(_extractor.compute(stream), dtype=np.float32))


def seconds(pcm16le: bytes, rate: int) -> float:
    return len(pcm16le) // 2 / rate


def identify(emb: np.ndarray) -> Match:
    best, best_score, second = None, 0.0, 0.0
    for name, rec in _speakers.items():
        score = float(np.dot(emb, np.array(rec["centroid"], dtype=np.float32)))
        if score > best_score:
            best, best_score, second = name, score, best_score
        elif score > second:
            second = score
    if best is not None and best_score >= THRESHOLD:
        return Match(best, best_score, _speakers[best].get("role", "member"), margin=best_score - second)
    return Match(None, best_score)


def enroll(name: str, embeddings: list[np.ndarray], role: str = "member") -> None:
    """Salva (o sostituisce) la persona con la media dei suoi embedding."""
    centroid = _unit(np.mean(embeddings, axis=0))
    _speakers[name] = {"centroid": centroid.tolist(), "samples": len(embeddings), "role": role}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(_speakers), encoding="utf-8")
    log.info("registrata la voce di %s (%d campioni)", name, len(embeddings))


def names() -> list[dict]:
    return [{"name": n, "samples": r["samples"], "role": r.get("role", "member")} for n, r in _speakers.items()]


def rename(old: str, new: str) -> bool:
    """Rinomina una persona (sostituisce un eventuale profilo omonimo)."""
    if old not in _speakers:
        return False
    _speakers[new] = _speakers.pop(old)
    STORE.write_text(json.dumps(_speakers), encoding="utf-8")
    return True


def delete(name: str) -> bool:
    if _speakers.pop(name, None) is None:
        return False
    STORE.write_text(json.dumps(_speakers), encoding="utf-8")
    return True
