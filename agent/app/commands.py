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
import tempfile
import time
from urllib.parse import urlsplit

from google.adk.tools import BaseTool
from google.genai import types

log = logging.getLogger("commands")

TIMEOUT_S = float(os.getenv("SKILL_CMD_TIMEOUT_S", "10"))
MAX_OUT = 64 * 1024
MAX_RESULT_CHARS = int(os.getenv("SKILL_MAX_RESULT_CHARS", "1500"))
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


def check_curl(args: list[str], hosts: list[str]) -> str:
    """Valida gli argomenti di curl. Ritorna '' se ok, altrimenti il motivo del rifiuto."""
    if not hosts:
        return "curl richiede 'allowed_hosts' nella skill"
    urls: list[str] = []
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
            if name in _CURL_DATA and data_bad(name, val):
                return "non si possono inviare file"
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
                    if ch == "d" and data_bad("-d", val):
                        return "non si possono inviare file"
                    break
        else:
            urls.append(a)
        i += 1
    if not urls:
        return "manca l'URL"
    for u in urls:
        if why := _host_ok(u, hosts):
            return why
    return ""


class RunTool(BaseTool):
    """Un tool per skill: `comando` = riga di comando con uno degli eseguibili ammessi."""

    def __init__(self, skill: str, allow: list[str], hosts: list[str], env_names: list[str], gate):
        super().__init__(
            name=f"esegui_{skill}",
            description=(f"Esegue un comando per la skill {skill}. Eseguibili ammessi: {', '.join(allow)}. "
                         "Non c'è una shell: niente pipe, redirezioni, variabili o sostituzioni. "
                         "Passa una sola riga con eseguibile e argomenti."))
        self.skill, self.allow, self.hosts, self.env_names, self.gate = skill, allow, hosts, env_names, gate

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description,
            parameters=types.Schema(type=types.Type.OBJECT, required=["comando"], properties={
                "comando": types.Schema(type=types.Type.STRING, description="Riga di comando, es. curl -s URL")}))

    async def process_llm_request(self, *, tool_context, llm_request) -> None:
        if self.gate(self.skill):
            await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)

    async def run_async(self, *, args, tool_context):
        t0 = time.monotonic()
        res = await self._run(str(args.get("comando", "")))
        log.info("comando (%s): %s in %.0f ms", self.skill, "errore" if "error" in res else "ok",
                 (time.monotonic() - t0) * 1000)
        return res

    async def _run(self, line: str) -> dict:
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
        if exe not in self.allow or "/" in exe:
            return {"error": f"eseguibile non ammesso: {exe}"}
        if exe == "curl" and (why := check_curl(rest, self.hosts)):
            return {"error": why}
        path = shutil.which(exe, path=SAFE_PATH)
        if not path:
            return {"error": f"{exe} non è installato"}
        secrets = [os.environ[n] for n in self.env_names if os.environ.get(n)]
        work = tempfile.mkdtemp(prefix="skill-")
        root = os.geteuid() == 0
        if root:   # via i privilegi: l'utente senza permessi non legge /data ne' /proc dell'agente
            os.chown(work, UID, GID)
        env = {"PATH": SAFE_PATH, "HOME": work, "LANG": "C.UTF-8", **{n: os.environ[n] for n in self.env_names if n in os.environ}}
        try:
            proc = await asyncio.create_subprocess_exec(
                path, *rest, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, cwd=work, env=env, preexec_fn=_limits, start_new_session=True)
            out = b""
            try:
                async with asyncio.timeout(TIMEOUT_S):
                    while len(out) < MAX_OUT and (chunk := await proc.stdout.read(8192)):
                        out += chunk
                    await proc.wait() if len(out) < MAX_OUT else None
            except TimeoutError:
                return {"error": "comando troppo lento"}
            finally:
                if proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.wait()
        except OSError:
            return {"error": "impossibile eseguire il comando"}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        text = out.decode("utf-8", "replace")
        for s in secrets:   # un comando potrebbe stampare il proprio token: non deve arrivare all'LLM ne' alla voce
            text = text.replace(s, "***")
        text = text[:MAX_RESULT_CHARS]
        if proc.returncode != 0:
            return {"error": f"codice di uscita {proc.returncode}", "output": text}
        return {"result": text}
