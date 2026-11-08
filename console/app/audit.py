"""Registro delle azioni sensibili (rivelazione di dati personali, caricamento skill, ricarica).

Una riga JSON per evento, in CONSOLE_AUDIT (volume dedicato). Non registra mai il contenuto
delle memorie: solo chi ha fatto cosa e su quale elemento.
"""
import json
import os
import threading
import time
from pathlib import Path

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.getenv("CONSOLE_AUDIT", "/data/audit.jsonl"))


def record(action: str, **detail) -> None:
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "action": action, **detail},
                      ensure_ascii=False)
    with _lock:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def tail(limit: int = 200) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    with _lock:
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for raw in reversed(lines):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out
