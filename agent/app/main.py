"""API HTTP per l'ESP32: POST /v1/utterance (PCM16 16 kHz mono, anche chunked) -> JSON."""
import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.requests import ClientDisconnect
from pydantic import BaseModel

from . import enrollment, memory, speaker, stt, tts
from .agent import Assistant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("api")

MIN_MS, MAX_MS = 200, 30_000
assistant: Assistant


@asynccontextmanager
async def lifespan(_: FastAPI):
    global assistant
    await asyncio.to_thread(stt.load)  # evita la latenza del primo enunciato
    if speaker.enabled():
        await asyncio.to_thread(speaker.load)
    assistant = Assistant()
    cleaner = None
    if memory.enabled():
        try:
            await memory.start()
            cleaner = asyncio.create_task(memory.cleanup_loop())
        except Exception:   # Qdrant spento: l'assistente funziona comunque, senza preferenze
            log.exception("memoria non disponibile, continuo senza preferenze")
            memory.URL = ""
    yield
    if cleaner:
        cleaner.cancel()
        await memory.stop()


app = FastAPI(title="JARVIS agent", lifespan=lifespan)


def check_auth(req: Request) -> None:
    token = os.getenv("AGENT_TOKEN", "")
    if token and not hmac.compare_digest(req.headers.get("authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "token non valido")


def device_id(req: Request) -> str:
    return req.headers.get("x-device-id") or (req.client.host if req.client else "unknown")


def result(transcript: str, reply: str, follow_up: bool | None = None, who: speaker.Match | None = None) -> dict:
    # "label" e "audio" restano per primi: il firmware li cerca nei primi 512 byte.
    reply = tts.speech_text(reply)
    out: dict = {"label": "ok"}
    if reply and tts.enabled():
        out["audio"] = f"/v1/reply/{tts.register(reply)}"   # PCM16 16 kHz mono, scaricabile con GET
    # Domanda o richiesta di chiarimento: il dispositivo resta in ascolto senza nuova wake word.
    out["follow_up"] = reply.rstrip().endswith("?") if follow_up is None else follow_up
    if who is not None:   # "role" servirà per limitare in futuro alcune funzioni a certe persone
        out["speaker"] = {"name": who.name, "score": round(who.score, 2), "role": who.role}
    return out | {"transcript": transcript, "reply": reply}


@app.get("/healthz", status_code=204)
async def healthz() -> None:
    return None


@app.post("/v1/utterance")
async def utterance(req: Request, rate: int = 16000) -> dict:
    check_auth(req)
    if not 8000 <= rate <= 48000:
        raise HTTPException(400, "rate non valido")
    limit = MAX_MS * rate // 1000 * 2
    buf = bytearray()
    try:
        async for chunk in req.stream():
            buf += chunk
            if len(buf) > limit:
                raise HTTPException(413, "audio troppo lungo")
    except ClientDisconnect:   # il dispositivo ha annullato la sessione (nessun parlato dopo la wake word)
        raise HTTPException(499, "client disconnesso")
    ms = len(buf) // 2 * 1000 // rate
    if ms < MIN_MS:
        raise HTTPException(400, f"audio troppo corto ({ms} ms)")

    pcm = bytes(buf)
    dev = device_id(req)
    t_end = time.monotonic()   # l'ESP32 ha chiuso lo stream: da qui in poi e' latenza percepita

    async def identify() -> speaker.Match | None:
        if not speaker.enabled() or enrollment.active(dev) or speaker.seconds(pcm, rate) < speaker.MIN_SECONDS:
            return None
        emb = await asyncio.to_thread(speaker.embed, pcm, rate)
        return speaker.identify(emb)

    async def timed(coro):
        r = await coro
        return r, time.monotonic() - t_end

    (text, t_stt), (who, t_spk) = await asyncio.gather(
        timed(asyncio.to_thread(stt.transcribe, pcm, rate)), timed(identify()))
    log.info("%s: %d ms -> %r (voce: %s %.2f)", dev, ms, text,
             who.name if who else "-", who.score if who else 0)

    if (flow := await asyncio.to_thread(enrollment.handle, dev, text, pcm, rate)) is not None:
        log.info("registrazione voce: %r", flow[0])
        return result(text, flow[0], follow_up=flow[1])
    if not text:
        return result("", "")
    t0 = time.monotonic()
    # Preferenze solo con parlante noto E sicuro (soglia e margine piu' severi del semplice riconoscimento).
    user = who.name if who and memory.enabled() and memory.personalize_ok(who.name, who.score, who.margin) else None
    mems: list[str] = []
    if user:
        try:
            mems = await memory.retrieve(user, text)
        except Exception:
            log.exception("recupero memorie fallito")
    reply = await assistant.ask(dev, text, who.name if who else None, memories=mems)
    if user:   # dopo la risposta, senza bloccarla
        asyncio.create_task(memory.observe(user, text, dev))
    log.info("risposta: %r", reply)
    log.info("TEMPI stt=%.1fs voce=%.1fs llm=%.1fs totale=%.1fs (audio %d ms)",
             t_stt, t_spk, time.monotonic() - t0, time.monotonic() - t_end, ms)
    return result(text, reply, who=who)


class TextIn(BaseModel):
    text: str


@app.post("/v1/text")
async def text(req: Request, body: TextIn) -> dict:
    """Come /v1/utterance ma con testo già trascritto (utile per test con curl)."""
    check_auth(req)
    return result(body.text, await assistant.ask(device_id(req), body.text))


@app.get("/v1/reply/{rid}")
async def reply_audio(req: Request, rid: str) -> Response:
    """Audio della risposta (PCM16LE mono 16 kHz) generato da ElevenLabs e consegnato per intero."""
    check_auth(req)
    pcm = await tts.fetch(rid)   # intero clip: l'ESP32 lo scarica a velocità Wi-Fi
    if pcm is None:
        raise HTTPException(404, "risposta scaduta o inesistente")
    if not pcm:
        raise HTTPException(502, "sintesi vocale non disponibile")
    return Response(pcm, media_type="audio/L16;rate=16000")


@app.get("/v1/speakers")
async def list_speakers(req: Request) -> list[dict]:
    check_auth(req)
    return speaker.names()


@app.post("/v1/speakers/{name}/rename", status_code=204)
async def rename_speaker(req: Request, name: str, to: str) -> None:
    check_auth(req)
    if not speaker.rename(name, to):
        raise HTTPException(404, "persona non registrata")


@app.delete("/v1/speakers/{name}", status_code=204)
async def delete_speaker(req: Request, name: str) -> None:
    check_auth(req)
    if not speaker.delete(name):
        raise HTTPException(404, "persona non registrata")


class MemoryIn(BaseModel):
    user: str
    text: str
    pinned: bool = False


def _need_memory() -> None:
    if not memory.enabled():
        raise HTTPException(503, "memoria non configurata (QDRANT_URL)")


@app.get("/v1/memories")
async def list_memories(req: Request, user: str, status: str | None = None) -> list[dict]:
    check_auth(req)
    _need_memory()
    return await memory.list_memories(user, status)


@app.post("/v1/memories")
async def add_memory(req: Request, body: MemoryIn) -> dict:
    """Inserimento manuale (attivo subito); con pinned=true viene sempre iniettata e non scade."""
    check_auth(req)
    _need_memory()
    return {"id": await memory.add(body.user, body.text, pinned=body.pinned)}


@app.delete("/v1/memories/{mid}", status_code=204)
async def delete_memory(req: Request, mid: str) -> None:
    check_auth(req)
    _need_memory()
    if not await memory.delete(mid):
        raise HTTPException(404, "memoria inesistente")


@app.delete("/v1/memories", status_code=204)
async def purge_memories(req: Request, user: str) -> None:
    """Oblio totale delle memorie di una persona."""
    check_auth(req)
    _need_memory()
    await memory.purge_user(user)
