"""Embedding locali condivisi (fastembed, ONNX): usati da memoria utente e attivazione delle skill."""
import asyncio
import os

NAME = os.getenv("MEMORY_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CACHE = os.getenv("FASTEMBED_CACHE_PATH", "/models/fastembed")
_model = None


async def load() -> None:
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = await asyncio.to_thread(TextEmbedding, model_name=NAME, cache_dir=CACHE)


def ready() -> bool:
    return _model is not None


async def embed(text: str) -> list[float]:
    vec = await asyncio.to_thread(lambda: next(iter(_model.embed([text]))))
    return [float(x) for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-9)
