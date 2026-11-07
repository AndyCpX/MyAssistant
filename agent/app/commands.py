"""Comandi scelti dall'LLM per una skill.

Ogni skill dichiara quali eseguibili ammette (e per curl quali host). Il comando e' una riga che viene spezzata con shlex
ed eseguita SENZA shell, come utente senza privilegi, con ambiente ripulito (solo le variabili dichiarate dalla skill),
in una cartella temporanea, con timeout e limiti. Segreti e output sensibili non finiscono nei log.

Limiti noti: con argomenti liberi l'LLM puo' fare tutto cio' che l'eseguibile consente verso gli host ammessi.
Per curl i flag pericolosi sono vietati e gli URL controllati; per gli altri eseguibili vale solo l'allowlist.
"""
import asyncio
import fnmatch
import logging
import os
import re
import resource
import shlex
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from google.adk.tools import BaseTool
from google.genai import types

log = logging.getLogger("commands")

TIMEOUT_S = float(os.getenv("SKILL_CMD_TIMEOUT_S", "10"))
MAX_OUT = 64 * 1024
MAX_RESULT_CHARS = int(os.getenv("SKILL_MAX_RESULT_CHARS", "3000"))
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
UID = GID = int(os.getenv("SKILL_CMD_UID", "65534"))   # nobody

_VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")
_CURL_DENY_SHORT = set("KoOTxFLbcDv")   # config, output, upload, proxy, form, redirect, cookie, dump-header, verbose
_CURL_VALUE_SHORT = set("HdXmAuewr")
_CURL_DENY_LONG = {
    "--config", "--output", "--remote-name", "--remote-name-all", "--upload-file", "--proxy", "--preproxy", "--unix-socket",
    "--form", "--form-string", "--location", "--location-trusted", "--cookie", "--cookie-jar", "--dump-header", "--trace",
    "--trace-ascii", "--trace-time", "--verbose", "--stderr", "--netrc", "--netrc-file", "--resolve", "--connect-to",
    "--libcurl", "--next", "--create-dirs", "--output-dir", "--hsts", "--alt-svc", "--proxy-user", "--abstract-unix-socket",
}
_CURL_VALUE_LONG = {
    "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json", "--request", "--max-time",
    "--connect-timeout", "--user-agent", "--user", "--referer", "--write-out", "--retry", "--retry-delay", "--url",
}
_CURL_DATA = {"--data", "--data-raw", "--data-binary", "--data-urlencode", "--json"}


def _limits() -> None:   # eseguito nel figlio prima dell'exec (preexec_fn: funziona anche con uvloop)
    if os.geteuid() == 0:   # via i privilegi: l'utente senza permessi non legge /data ne' /proc dell'agente
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    resource.setrlimit(resource.RLIMIT_CPU, (int(TIMEOUT_S) + 2,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_AS, (512 << 20,) * 2)


def _host_ok(url: str, hosts: list[str]) -> str:
    """'' se l'URL e' ammesso, altrimenti il motivo."""
    if any(c in url for c in "{}[]"):
        return "URL con caratteri di espansione non ammessi"
    sp = urlsplit(url if "://" in url else "http://" + url)
    if sp.scheme not in ("http", "https") or not sp.hostname:
        return "solo URL http/https"
    try:
        port = sp.port
    except ValueError:
        return "porta non valida"
    for h in hosts:
        if ":" in h:
            if fnmatch.fnmatch(f"{sp.hostname}:{port or ''}", h):
                return ""
        elif fnmatch.fnmatch(sp.hostname, h):
            return ""
    return f"host non ammesso: {sp.hostname}"


def check_curl(args: list[str], hosts: list[str], rules: list | None = None) -> str:
    """Valida gli argomenti di curl. Ritorna '' se ok, altrimenti il motivo del rifiuto.

    `rules`: lista di (metodo, regex) sul percorso dell'URL; se presente, ogni URL deve corrispondere a una regola con il
    metodo effettivo (-X, altrimenti POST se ci sono dati, altrimenti GET). Sono ammessi solo GET e POST.
    """
    if not hosts:
        return "curl richiede 'allowed_hosts' nella skill"
    urls: list[str] = []
    method, has_data = "", False
    i = 0

    def data_bad(flag: str, val: str) -> bool:
        return val.startswith("@") or (flag in ("--data-urlencode",) and "@" in val)

    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            name, _, val = a.partition("=")
            has_val = "=" in a
            if name in _CURL_DENY_LONG:
                return f"opzione non ammessa: {name}"
            if name in _CURL_VALUE_LONG and not has_val:
                i += 1
                val = args[i] if i < len(args) else ""
            if name in _CURL_DATA:
                has_data = True
                if data_bad(name, val):
                    return "non si possono inviare file"
            if name == "--request":
                method = val.upper()
            if name == "--url":
                urls.append(val)
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:]):
                if ch in _CURL_DENY_SHORT:
                    return f"opzione non ammessa: -{ch}"
                if ch in _CURL_VALUE_SHORT:
                    val = a[j + 2:]
                    if not val:
                        i += 1
                        val = args[i] if i < len(args) else ""
                    if ch == "d":
                        has_data = True
                        if data_bad("-d", val):
                            return "non si possono inviare file"
                    if ch == "X":
                        method = val.upper()
                    break
        else:
            urls.append(a)
        i += 1
    if not urls:
        return "manca l'URL"
    for u in urls:
        if why := _host_ok(u, hosts):
            return why
    method = method or ("POST" if has_data else "GET")
    if method not in ("GET", "POST"):
        return f"metodo non ammesso: {method}"
    if rules:
        for u in urls:
            path = urlsplit(u if "://" in u else "http://" + u).path or "/"
            if not any(m == method and rx.fullmatch(path) for m, rx in rules):
                return f"richiesta non ammessa dalla skill: {method} {path}"
    return ""


MAX_PIPE = 8 * 1024 * 1024   # output di un comando che passa per un filtro jq (l'output finale resta piccolo)


async def _exec(path: str, args: list[str], env: dict, work: str, stdin: bytes | None, cap: int):
    """Esegue un processo (stdout e stderr separati, a dimensione limitata). Ritorna (codice, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        path, *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=work, env=env,
        preexec_fn=_limits, start_new_session=True)

    async def feed() -> None:
        if stdin is not None:
            try:
                proc.stdin.write(stdin)
                await proc.stdin.drain()
                proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def read(stream, limit: int) -> bytes:
        buf = b""
        while len(buf) < limit and (chunk := await stream.read(8192)):
            buf += chunk
        return buf

    try:
        async with asyncio.timeout(TIMEOUT_S):
            _, out, err = await asyncio.gather(feed(), read(proc.stdout, cap), read(proc.stderr, 8192))
            if len(out) < cap:
                await proc.wait()
    finally:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
    return proc.returncode, out, err


class RunTool(BaseTool):
    """Un tool per skill: `comando` = riga con un eseguibile ammesso o uno script della skill; `filtro_jq` opzionale."""

    def __init__(self, skill: str, allow: list[str], hosts: list[str], env_names: list[str], gate,
                 scripts: list[str] | None = None, folder: Path | None = None, rules: list | None = None):
        self.scripts: dict[str, Path] = {}
        for s in scripts or []:   # solo file .py dentro la cartella della skill: niente python3 con argomenti liberi
            p = (folder / s).resolve() if folder else None
            if p is None or not p.is_file() or p.suffix != ".py" or folder.resolve() not in p.parents:
                raise ValueError(f"script non valido: {s}")
            self.scripts[s] = self.scripts[p.name] = p
        parts = []
        if allow:
            parts.append("Eseguibili ammessi: " + ", ".join(allow) + ".")
        if scripts:
            parts.append("Script ammessi (scrivi il nome dello script seguito dagli argomenti): " + ", ".join(scripts) + ".")
        if "jq" in allow:
            parts.append("Per output grandi passa `filtro_jq` (filtro jq applicato all'output del comando): "
                         "non c'è una shell, quindi niente pipe.")
        super().__init__(name="esegui_" + re.sub(r"\W", "_", skill),
                         description=f"Esegue un comando per la skill {skill}. " + " ".join(parts) +
                                     " Niente pipe, redirezioni, variabili o sostituzioni. Una sola riga.")
        self.skill, self.allow, self.hosts, self.env_names, self.gate = skill, allow, hosts, env_names, gate
        self.rules = rules or []

    def _get_declaration(self) -> types.FunctionDeclaration:
        props = {"comando": types.Schema(type=types.Type.STRING, description="Riga di comando")}
        if "jq" in self.allow:
            props["filtro_jq"] = types.Schema(type=types.Type.STRING, description="Filtro jq opzionale sull'output")
        return types.FunctionDeclaration(
            name=self.name, description=self.description,
            parameters=types.Schema(type=types.Type.OBJECT, required=["comando"], properties=props))

    async def process_llm_request(self, *, tool_context, llm_request) -> None:
        if self.gate(self.skill):
            await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)

    async def run_async(self, *, args, tool_context):
        t0 = time.monotonic()
        res = await self._run(str(args.get("comando", "")), str(args.get("filtro_jq") or ""))
        if os.getenv("SKILL_LOG_COMMANDS") == "1":   # solo per debug: la riga ha i segnaposto ($TOKEN), non i valori
            log.info("comando scritto dall'LLM (%s): %s | filtro: %s", self.skill, args.get("comando"), args.get("filtro_jq"))
        if "error" in res:   # motivo del rifiuto o dell'errore (testo nostro o codice di uscita, senza segreti)
            log.info("comando (%s) rifiutato/fallito: %s", self.skill, res["error"])
        log.info("comando (%s): %s in %.0f ms", self.skill, "errore" if "error" in res else "ok",
                 (time.monotonic() - t0) * 1000)
        return res

    async def _run(self, line: str, jq_filter: str = "") -> dict:
        try:
            argv = shlex.split(line)
        except ValueError:
            return {"error": "comando non valido"}
        if not argv:
            return {"error": "comando vuoto"}
        exe, rest = argv[0], argv[1:]
        subst = {n: os.environ[n] for n in self.env_names if n in os.environ}
        if subst:   # il sistema espande solo le variabili dichiarate dalla skill: l'LLM scrive $NOME e non vede mai il valore
            rest = [_VAR.sub(lambda m: subst.get(m.group(1) or m.group(2), m.group(0)), a) for a in rest]
        if exe in self.scripts:
            path, rest = sys.executable, ["-I", str(self.scripts[exe]), *rest]   # -I: ignora PYTHON* e il sito utente
        elif exe not in self.allow or "/" in exe:
            return {"error": f"eseguibile non ammesso: {exe}"}
        else:
            if exe == "curl" and (why := check_curl(rest, self.hosts, self.rules)):
                return {"error": why}
            path = shutil.which(exe, path=SAFE_PATH)
            if not path:
                return {"error": f"{exe} non è installato"}
        if jq_filter:
            if "jq" not in self.allow:
                return {"error": "filtro_jq non ammesso per questa skill"}
            if jq_filter.lstrip().startswith("-") or len(jq_filter) > 2000:
                return {"error": "filtro jq non valido"}
        secrets = [os.environ[n] for n in self.env_names if os.environ.get(n)]
        work = tempfile.mkdtemp(prefix="skill-")
        if os.geteuid() == 0:
            os.chown(work, UID, GID)
        env = {"PATH": SAFE_PATH, "HOME": work, "LANG": "C.UTF-8", **subst}
        try:
            rc, out, err = await _exec(path, rest, env, work, None, MAX_PIPE if jq_filter else MAX_OUT)
            if jq_filter and rc == 0:   # secondo stadio: jq senza variabili segrete nell'ambiente
                jq = shutil.which("jq", path=SAFE_PATH)
                rc, out, err = await _exec(jq, ["-c", jq_filter], {k: v for k, v in env.items() if k not in subst},
                                           work, out, MAX_OUT)
        except TimeoutError:
            return {"error": "comando troppo lento"}
        except OSError:
            return {"error": "impossibile eseguire il comando"}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        text = (out + (b"\n" + err if err else b"")).decode("utf-8", "replace")
        for s in secrets:   # un comando potrebbe stampare il proprio token: non deve arrivare all'LLM ne' alla voce
            text = text.replace(s, "***")
        text = text.strip()[:MAX_RESULT_CHARS]
        if rc != 0:
            return {"error": f"codice di uscita {rc}", "output": text}
        return {"result": text}
