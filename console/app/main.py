"""Console di diagnostica di JARVIS (uso personale, sola lettura + caricamento skill).

- dispositivi, persone, memorie e notifiche letti dalle API di agente e notify;
- il testo di memorie e promemoria personali e' nascosto finche' non lo si richiede esplicitamente
  (?reveal=1), e ogni rivelazione finisce nell'audit log;
- caricamento di una skill da zip (solo tipi sicuri, vedi skill_upload.py), poi ricarica dell'agente.

Accesso: `Authorization: Bearer CONSOLE_TOKEN`. Il servizio va raggiunto solo da localhost.
"""
import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from . import audit, backend, skill_upload

log = logging.getLogger("console")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# httpx scrive l'URL di ogni richiesta: con i nomi delle persone nel percorso, non li vogliamo nei log.
logging.getLogger("httpx").setLevel(logging.WARNING)

STATIC = Path(__file__).parent / "static"
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "/srv/skills"))
REDACTED = "[nascosto: usa 'mostra' per vedere il testo]"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not os.getenv("CONSOLE_TOKEN", ""):
        raise RuntimeError("CONSOLE_TOKEN non impostato")   # dati personali: mai senza accesso protetto
    yield


app = FastAPI(title="JARVIS console", lifespan=lifespan)


def check_auth(req: Request) -> None:
    token = os.getenv("CONSOLE_TOKEN", "")
    if not token or not hmac.compare_digest(req.headers.get("authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "token non valido")


def _svc(e: backend.ServiceError) -> HTTPException:
    return HTTPException(502, str(e))


def _redact_memory(m: dict) -> dict:
    out = dict(m)
    out["text_len"] = len(m.get("text") or "")
    out["text"] = REDACTED
    return out


@app.get("/healthz", status_code=204)
def healthz() -> Response:
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health(req: Request) -> dict:
    check_auth(req)
    return await backend.health()


@app.get("/api/devices")
async def devices(req: Request) -> list[dict]:
    check_auth(req)
    try:
        return await backend.agent("GET", "/v1/devices") or []
    except backend.ServiceError as e:
        raise _svc(e)


@app.get("/api/persons")
async def persons(req: Request) -> list[dict]:
    """Persone registrate con il conteggio delle memorie per stato. Nessun testo, nessuna voce."""
    check_auth(req)
    try:
        speakers = await backend.agent("GET", "/v1/speakers") or []
        mems = await asyncio.gather(*[
            backend.agent("GET", "/v1/memories", params={"user": s["name"]}) for s in speakers])
    except backend.ServiceError as e:
        raise _svc(e)
    out = []
    for s, items in zip(speakers, mems):
        counts: dict[str, int] = {}
        for m in items or []:
            counts[m.get("status", "?")] = counts.get(m.get("status", "?"), 0) + 1
        out.append({**s, "memories": counts})
    return out


@app.get("/api/persons/{name}/memories")
async def person_memories(req: Request, name: str, reveal: bool = Query(default=False),
                          status: str | None = None) -> list[dict]:
    check_auth(req)
    params = {"user": name} | ({"status": status} if status else {})
    try:
        items = await backend.agent("GET", "/v1/memories", params=params) or []
    except backend.ServiceError as e:
        raise _svc(e)
    if reveal:
        audit.record("rivela_memorie", persona=name, quante=len(items))
        return items
    return [_redact_memory(m) for m in items]


@app.get("/api/notifications")
async def notifications(req: Request, reveal: bool = Query(default=False),
                        limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    check_auth(req)
    try:
        items = (await backend.notify("GET", "/v1/notifications", params={"limit": limit}) or {}).get("items", [])
    except backend.ServiceError as e:
        raise _svc(e)
    if reveal:
        audit.record("rivela_notifiche", quante=len(items))
        return items
    # Il testo dei promemoria personali e' nascosto; quello per tutti resta visibile.
    return [({**n, "text": REDACTED} if str(n.get("target", "")).startswith("person:") else n) for n in items]


@app.get("/api/skills")
async def skills(req: Request) -> list[dict]:
    check_auth(req)
    try:
        return await backend.agent("GET", "/v1/skills") or []
    except backend.ServiceError as e:
        raise _svc(e)


MAX_UPLOAD = skill_upload.MAX_ZIP_BYTES


@app.post("/api/skills/upload")
async def upload_skill(req: Request, filename: str = Query(default="skill.zip", max_length=120)) -> dict:
    """Corpo: il file zip (Content-Type application/zip). Installa e ricarica l'agente."""
    check_auth(req)
    length = int(req.headers.get("content-length") or 0)
    if length > MAX_UPLOAD:
        raise HTTPException(413, "zip troppo grande (max 5 MB)")
    data = await req.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "zip troppo grande (max 5 MB)")
    try:
        installed = skill_upload.install(data, filename, SKILLS_DIR)
    except skill_upload.UploadError as e:
        audit.record("skill_rifiutata", file=filename, motivo=str(e))
        raise HTTPException(422, str(e))
    audit.record("skill_caricata", **installed, file=filename)
    try:
        await backend.agent("POST", "/v1/skills/reload")
        reload_state = "ricaricata"
    except backend.ServiceError as e:
        reload_state = f"installata ma ricarica fallita: {e}"
    entry = next((s for s in await skills_safe() if s.get("name") == installed["name"]), None)
    return {**installed, "reload": reload_state, "stato": entry}


async def skills_safe() -> list[dict]:
    try:
        return await backend.agent("GET", "/v1/skills") or []
    except backend.ServiceError:
        return []


@app.post("/api/skills/reload")
async def reload_skills(req: Request) -> dict:
    check_auth(req)
    try:
        result = await backend.agent("POST", "/v1/skills/reload")
    except backend.ServiceError as e:
        raise _svc(e)
    audit.record("skill_ricaricate")
    return {"skills": result or []}


@app.get("/api/audit")
async def audit_log(req: Request, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    check_auth(req)
    return audit.tail(limit)
