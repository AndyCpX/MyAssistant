"""Memoria delle preferenze utente (Qdrant + embedding locali con fastembed).

- Le preferenze esplicite ("ricordati che...") sono attive subito.
- Quelle dedotte restano "candidate" (mai usate nelle risposte) finche' non si ripetono MEMORY_PROMOTE_AFTER volte.
- Scadenza scorrevole di MEMORY_TTL_DAYS giorni (rinnovata a ogni uso). Le "pinned" non scadono.
- Il testo delle memorie e' dato personale: resta solo in locale e non va mai scritto nei log.
Vedi knowledge/agent/user-memory.md.
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid

import litellm
from qdrant_client import AsyncQdrantClient, models

from . import embed as embedder

log = logging.getLogger("memory")

URL = os.getenv("QDRANT_URL", "")
COLLECTION = os.getenv("MEMORY_COLLECTION", "user_memories")
DIM = 384

DAY = 86400
TTL_S = int(float(os.getenv("MEMORY_TTL_DAYS", "90")) * DAY)
CANDIDATE_TTL_S = int(float(os.getenv("MEMORY_CANDIDATE_TTL_DAYS", "30")) * DAY)
PROMOTE_AFTER = int(os.getenv("MEMORY_PROMOTE_AFTER", "2"))
REPEAT_GAP_S = int(os.getenv("MEMORY_REPEAT_GAP_S", "600"))   # ripetizioni piu' ravvicinate = stessa conversazione
TOP_K = int(os.getenv("MEMORY_TOP_K", "4"))
MIN_SCORE = float(os.getenv("MEMORY_MIN_SCORE", "0.30"))      # rilevanza minima per iniettare (da calibrare)
SAME_SCORE = float(os.getenv("MEMORY_SAME_SCORE", "0.85"))    # sopra questa similarita' = stessa informazione (da calibrare)
FORGET_SCORE = float(os.getenv("MEMORY_FORGET_SCORE", "0.6"))
PERSONALIZATION_THRESHOLD = float(os.getenv("PERSONALIZATION_THRESHOLD", "0.75"))
SPEAKER_MARGIN = float(os.getenv("PERSONALIZATION_MARGIN", "0.05"))

_client: AsyncQdrantClient | None = None

_REMEMBER = re.compile(r"\b(?:ricordati|ricorda|tieni presente|tieni a mente|memorizza)\s+(?:che\s+)?(.+)", re.I | re.S)
_FORGET = re.compile(r"\b(?:dimentica|scordati|cancella dalla memoria)\s+(?:che\s+)?(.+)", re.I | re.S)

_EXTRACT_PROMPT = (
    "Estrai da un enunciato vocale le informazioni DUREVOLI sull'utente che parla (preferenze, abitudini, fatti personali, "
    "persone o animali vicini a lui, modo in cui vuole le risposte). Ignora richieste momentanee, domande, meteo, orari. "
    "Il testo e' una trascrizione automatica e puo' contenere errori. "
    'Rispondi SOLO con JSON: {"memories":[{"kind":"preference|fact|routine|relationship|style",'
    '"key":"area.attributo in minuscolo, es. music.genre","text":"frase breve in italiano in terza persona con il nome dell\'utente"}]}. '
    'Se non c\'e\' nulla di durevole rispondi {"memories":[]}.'
)


def enabled() -> bool:
    return bool(URL)


def personalize_ok(name: str | None, score: float, margin: float) -> bool:
    """Le preferenze si usano (e si scrivono) solo con parlante noto e sicuro: altrimenti l'utente e' 'ospite'."""
    return bool(name) and score >= PERSONALIZATION_THRESHOLD and margin >= SPEAKER_MARGIN


def _now() -> float:
    return time.time()


def _must() -> AsyncQdrantClient:
    assert _client is not None, "memoria non inizializzata"
    return _client


async def start() -> None:
    """Connette Qdrant, carica il modello di embedding e crea collezione e indici (idempotente)."""
    global _client

    await embedder.load()
    _client = AsyncQdrantClient(url=URL)
    if not await _client.collection_exists(COLLECTION):
        await _client.create_collection(
            COLLECTION, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    for field, schema in (("user_id", "keyword"), ("status", "keyword"), ("key", "keyword"),
                          ("pinned", "bool"), ("expires_ts", "float")):
        await _client.create_payload_index(COLLECTION, field_name=field, field_schema=schema)
    log.info("memoria pronta (%d punti)", (await _client.count(COLLECTION)).count)


async def stop() -> None:
    if _client:
        await _client.close()


async def embed(text: str) -> list[float]:
    return await embedder.embed(text)


def _flt(user: str, status: list[str] | None = None, pinned: bool | None = None, live: bool = True) -> models.Filter:
    must: list = [models.FieldCondition(key="user_id", match=models.MatchValue(value=user))]
    if status:
        must.append(models.FieldCondition(key="status", match=models.MatchAny(any=status)))
    if pinned is not None:
        must.append(models.FieldCondition(key="pinned", match=models.MatchValue(value=pinned)))
    if live:   # la scadenza vale anche se la pulizia periodica non e' ancora girata
        must.append(models.FieldCondition(key="expires_ts", range=models.Range(gt=_now())))
    return models.Filter(must=must)


NEVER = 9e15   # expires_ts delle memorie pinned


# ---------------------------------------------------------------- lettura

async def retrieve(user: str, text: str) -> list[str]:
    """Memorie attive pertinenti al testo + quelle pinned (testi pronti da iniettare nel prompt)."""
    vec = await embed(text)
    hits = (await _must().query_points(
        COLLECTION, query=vec, query_filter=_flt(user, ["active"], pinned=False), limit=TOP_K,
        score_threshold=MIN_SCORE, with_payload=True)).points
    pinned, _ = await _must().scroll(COLLECTION, scroll_filter=_flt(user, ["active"], pinned=True), limit=20)
    out = [p.payload["text"] for p in [*pinned, *hits]]
    now = _now()
    for p in hits:   # uso = rinnovo della scadenza
        asyncio.create_task(_touch(p.id, p.payload.get("use_count", 0) + 1, now))
    log.info("memoria: %d recuperate (%d pinned) per %s", len(out), len(pinned), user)
    return out


async def _touch(pid, use_count: int, now: float) -> None:
    try:
        await _must().set_payload(COLLECTION, {"last_used_at": now, "use_count": use_count,
                                               "expires_ts": now + TTL_S}, points=[pid])
    except Exception:   # best effort, mai bloccare la risposta
        log.exception("aggiornamento uso memoria fallito")


# ---------------------------------------------------------------- scrittura

async def _extract(user: str, utterance: str, explicit: bool) -> list[dict]:
    """Chiede all'LLM le informazioni durevoli. Ritorna [] se nulla o se la chiamata fallisce."""
    hint = " L'utente ha chiesto esplicitamente di ricordarlo: normalizza l'informazione." if explicit else ""
    kwargs = {}
    if os.getenv("LLM_THINK", "").lower() in ("0", "false", "no"):
        kwargs["think"] = False
    try:
        r = await litellm.acompletion(
            model=os.getenv("MEMORY_LLM_MODEL") or os.getenv("LLM_MODEL", "ollama_chat/gpt-oss:120b"),
            api_base=os.getenv("LLM_API_BASE", "https://ollama.com"),
            api_key=os.getenv("LLM_API_KEY") or None,
            max_tokens=400, temperature=0,
            messages=[{"role": "system", "content": _EXTRACT_PROMPT + hint},
                      {"role": "user", "content": f"Utente: {user}\nEnunciato: {utterance}"}],
            **kwargs)
        raw = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.S)
        items = json.loads(m.group(0)).get("memories", []) if m else []
        return [i for i in items if isinstance(i, dict) and i.get("text")]
    except Exception:
        log.exception("estrazione memorie fallita")
        return []


async def _similar(user: str, vec: list[float], status: list[str]):
    res = (await _must().query_points(
        COLLECTION, query=vec, query_filter=_flt(user, status), limit=1, score_threshold=SAME_SCORE,
        with_payload=True)).points
    return res[0] if res else None


async def _insert(user: str, item: dict, source: str, status: str, device: str | None,
                  pinned: bool = False, vec: list[float] | None = None) -> str:
    now = _now()
    pid = str(uuid.uuid4())
    ttl = NEVER if pinned else (TTL_S if status == "active" else CANDIDATE_TTL_S)
    payload = {
        "user_id": user, "kind": item.get("kind") or "fact", "key": item.get("key") or "", "text": item["text"],
        "pinned": pinned, "status": status, "supersedes": None, "source": source,
        "seen_count": 1, "device_id": device, "created_at": now, "updated_at": now, "last_seen_at": now,
        "last_used_at": None, "use_count": 0, "expires_ts": now + ttl if not pinned else NEVER,
    }
    await _must().upsert(COLLECTION, points=[models.PointStruct(id=pid, vector=vec or await embed(item["text"]),
                                                                payload=payload)])
    return pid


async def _supersede(user: str, key: str, new_id: str) -> None:
    """La memoria promossa sostituisce le attive con la stessa chiave."""
    if not key:
        return
    flt = _flt(user, ["active"])
    flt.must.append(models.FieldCondition(key="key", match=models.MatchValue(value=key)))
    old, _ = await _must().scroll(COLLECTION, scroll_filter=flt, limit=50)
    ids = [p.id for p in old if str(p.id) != new_id]
    if ids:
        await _must().set_payload(COLLECTION, {"status": "superseded", "expires_ts": _now() + CANDIDATE_TTL_S},
                                  points=ids)
        await _must().set_payload(COLLECTION, {"supersedes": str(ids[0])}, points=[new_id])


async def _store(user: str, item: dict, explicit: bool, device: str | None) -> None:
    vec = await embed(item["text"])
    key = item.get("key") or ""
    if explicit:   # attiva subito; se esiste gia' la stessa informazione si rinnova soltanto
        same = await _similar(user, vec, ["active"])
        if same:
            await _must().set_payload(COLLECTION, {"updated_at": _now(), "expires_ts": _now() + TTL_S},
                                      points=[same.id])
            return
        pid = await _insert(user, item, "explicit", "active", device, vec=vec)
        await _supersede(user, key, pid)
        log.info("memoria esplicita salvata per %s", user)
        return
    same = await _similar(user, vec, ["active", "candidate"])
    now = _now()
    if same is None:
        await _insert(user, item, "inferred", "candidate", device, vec=vec)
        log.info("candidato creato per %s", user)
        return
    p = same.payload
    if p["status"] == "active":   # gia' nota: rinnova la scadenza
        await _must().set_payload(COLLECTION, {"updated_at": now, "expires_ts": now + TTL_S}, points=[same.id])
        return
    if now - p.get("last_seen_at", 0) < REPEAT_GAP_S:   # stessa conversazione: non conta come ripetizione
        return
    seen = p.get("seen_count", 1) + 1
    upd: dict = {"seen_count": seen, "last_seen_at": now, "updated_at": now}
    if seen >= PROMOTE_AFTER:
        upd |= {"status": "active", "expires_ts": now + TTL_S}
    await _must().set_payload(COLLECTION, upd, points=[same.id])
    if seen >= PROMOTE_AFTER:
        await _supersede(user, p.get("key", ""), str(same.id))
        log.info("memoria promossa per %s dopo %d ripetizioni", user, seen)


async def _forget(user: str, what: str) -> int:
    vec = await embed(what)
    hits = (await _must().query_points(
        COLLECTION, query=vec, query_filter=_flt(user, ["active", "candidate"]), limit=3,
        score_threshold=FORGET_SCORE)).points
    if hits:
        await _must().set_payload(COLLECTION, {"status": "deleted", "expires_ts": _now() + DAY},
                                  points=[h.id for h in hits])
    log.info("dimenticate %d memorie di %s", len(hits), user)
    return len(hits)


async def observe(user: str, utterance: str, device: str | None = None) -> None:
    """Dopo la risposta, in background: ricorda/dimentica su richiesta oppure raccoglie candidati."""
    try:
        if m := _FORGET.search(utterance):
            await _forget(user, m.group(1).strip())
            return
        explicit = _REMEMBER.search(utterance)
        items = await _extract(user, utterance, explicit=bool(explicit))
        if not items and explicit:   # ripiego: l'LLM non ha risposto, ma la richiesta era esplicita
            items = [{"kind": "fact", "key": "", "text": f"{user} ha chiesto di ricordare: {explicit.group(1).strip()}"}]
        for it in items[:5]:
            await _store(user, it, explicit=bool(explicit), device=device)
    except Exception:
        log.exception("osservazione memoria fallita")


# ---------------------------------------------------------------- gestione

def _public(p) -> dict:
    d = dict(p.payload)
    d["id"] = str(p.id)
    return d


async def add(user: str, text: str, pinned: bool = False, kind: str = "fact", key: str = "") -> str:
    """Inserimento manuale (attivo subito)."""
    return await _insert(user, {"kind": kind, "key": key, "text": text}, "explicit", "active", None, pinned=pinned)


async def list_memories(user: str, status: str | None = None) -> list[dict]:
    flt = _flt(user, [status] if status else None, live=False)
    pts, _ = await _must().scroll(COLLECTION, scroll_filter=flt, limit=500, with_payload=True)
    return [_public(p) for p in pts]


async def delete(pid: str) -> bool:
    if not await _must().retrieve(COLLECTION, ids=[pid]):
        return False
    await _must().delete(COLLECTION, points_selector=models.PointIdsList(points=[pid]))
    return True


async def purge_user(user: str) -> None:
    await _must().delete(COLLECTION, points_selector=models.FilterSelector(filter=_flt(user, live=False)))


async def cleanup() -> None:
    """Elimina i punti scaduti (la lettura li ignora comunque)."""
    flt = models.Filter(must=[models.FieldCondition(key="expires_ts", range=models.Range(lte=_now()))])
    await _must().delete(COLLECTION, points_selector=models.FilterSelector(filter=flt))


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(DAY)
        try:
            await cleanup()
        except Exception:
            log.exception("pulizia memorie fallita")
