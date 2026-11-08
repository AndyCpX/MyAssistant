"""Caricamento di una skill da zip, con controlli prima di scrivere su disco.

Politica (v1): la skill entra solo se e' di tipo `instructions` o `http`. Le skill con codice
(file .py/.sh/..., tipo `python`, blocco `commands`) eseguono programmi nel container dell'agente:
sono rifiutate salvo CONSOLE_ALLOW_CODE_SKILLS=1.
"""
import io
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import yaml

MAX_ZIP_BYTES = 5 * 1024 * 1024
MAX_FILES = 200
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_RATIO = 100                       # byte scompressi / byte compressi: sopra = sospetta zip bomb
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
CODE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".ts", ".exe", ".bat", ".cmd", ".ps1", ".so", ".dll", ".pyc"}
ALLOWED_TYPES = {"instructions", "http"}
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n(.*))?\Z", re.S)


class UploadError(ValueError):
    """Motivo leggibile del rifiuto, mostrato all'utente."""


def _code_allowed() -> bool:
    return os.getenv("CONSOLE_ALLOW_CODE_SKILLS", "0") == "1"


def _safe_name(raw: str) -> str:
    """Nome cartella dalla stringa grezza (nome file o cartella dello zip)."""
    base = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")[:40]
    return base if NAME_RE.match(base) else ""


def _check_member(info: zipfile.ZipInfo) -> PurePosixPath | None:
    name = info.filename
    if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UploadError(f"percorso non ammesso: {name}")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise UploadError(f"link simbolico non ammesso: {name}")
    if info.is_dir():
        return None
    path = PurePosixPath(name)
    if not path.parts or any(p in ("..", ".") for p in path.parts):
        raise UploadError(f"percorso non ammesso: {name}")
    return path


def inspect(data: bytes, filename: str) -> dict:
    """Controlla lo zip senza estrarlo. Restituisce il piano di installazione."""
    if len(data) > MAX_ZIP_BYTES:
        raise UploadError("zip troppo grande (max 5 MB)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UploadError("il file non e' uno zip valido")
    infos = zf.infolist()
    files: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
    for info in infos:
        path = _check_member(info)
        if path is not None:
            files.append((path, info))
    if len(files) > MAX_FILES:
        raise UploadError(f"troppi file (max {MAX_FILES})")
    total = sum(i.file_size for _, i in files)
    packed = sum(max(i.compress_size, 1) for _, i in files)
    if total > MAX_TOTAL_BYTES or total > packed * MAX_RATIO:
        raise UploadError("contenuto non ammesso (troppo grande o compressione sospetta)")

    names = {p.as_posix() for p, _ in files}
    if "SKILL.md" in names:
        prefix, folder = "", _safe_name(Path(filename).stem)
    else:
        tops = {p.parts[0] for p, _ in files}
        if len(tops) != 1 or f"{next(iter(tops))}/SKILL.md" not in names:
            raise UploadError("SKILL.md non trovato (nella radice dello zip o in una sola cartella)")
        prefix, folder = f"{next(iter(tops))}/", _safe_name(next(iter(tops)))
    if not folder or not NAME_RE.match(folder):
        raise UploadError("nome della skill non valido (usa lettere minuscole, cifre, - e _)")

    kept = []
    for path, info in files:
        rel = path.as_posix()[len(prefix):] if prefix else path.as_posix()
        if PurePosixPath(rel).suffix.lower() in CODE_SUFFIXES and not _code_allowed():
            raise UploadError(f"file di codice non ammesso: {rel}")
        kept.append((rel, info))

    cfg, _ = _parse_manifest(zf, prefix)
    skill_type = _infer_type(cfg, {r for r, _ in kept})
    if skill_type not in ALLOWED_TYPES and not _code_allowed():
        raise UploadError(f"tipo di skill non ammesso: {skill_type}")
    if cfg.get("commands") and not _code_allowed():
        raise UploadError("le skill con 'commands' eseguono programmi: non ammesse")
    return {"folder": folder, "prefix": prefix, "files": kept, "type": skill_type, "zip": zf}


def _parse_manifest(zf: zipfile.ZipFile, prefix: str) -> tuple[dict, str]:
    try:
        text = zf.read(prefix + "SKILL.md").decode("utf-8").replace("\r\n", "\n")
    except (KeyError, UnicodeDecodeError):
        raise UploadError("SKILL.md non leggibile (UTF-8)")
    m = _FRONT.match(text)
    if not m:
        raise UploadError("frontmatter di SKILL.md mancante")
    try:
        cfg = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        raise UploadError("frontmatter YAML non valido")
    if not isinstance(cfg, dict):
        raise UploadError("frontmatter non valido")
    local = prefix + "skill.local.yaml"
    if local in zf.namelist():   # stessa regola dell'agente: il file locale completa il manifest
        try:
            extra = yaml.safe_load(zf.read(local).decode("utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            raise UploadError("skill.local.yaml non valido")
        if isinstance(extra, dict):
            cfg = {**cfg, **extra}
    return cfg, (m.group(2) or "").strip()


def _infer_type(cfg: dict, rel_files: set[str]) -> str:
    """Stessa logica di agent/app/skills.py::_infer_type."""
    if cfg.get("type"):
        return str(cfg["type"])
    if "tools.py" in rel_files:
        return "python"
    if any(isinstance(t, dict) for t in cfg.get("tools") or []):
        return "http"
    return "instructions"


def install(data: bytes, filename: str, skills_dir: Path) -> dict:
    """Installa la skill in skills_dir/<nome>. Non sovrascrive mai una skill esistente."""
    plan = inspect(data, filename)
    target = skills_dir / plan["folder"]
    if target.exists():
        raise UploadError(f"la skill '{plan['folder']}' esiste gia': rimuovila dal disco prima di ricaricarla")
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = skills_dir / f".staging-{uuid.uuid4().hex}"   # cartella nascosta: il caricatore la ignora
    try:
        for rel, info in plan["files"]:
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with plan["zip"].open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"name": plan["folder"], "type": plan["type"], "files": len(plan["files"])}
