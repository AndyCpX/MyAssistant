"""Coda delle notifiche su SQLite (stdlib). Nessuna dipendenza dall'agente o dai modelli.

Modello:
- una notifica ha un destinatario (`target`): "all", "device:<id>" oppure "person:<nome>";
- e' consegnabile quando `deliver_at` e' passato e non e' scaduta/annullata;
- ogni dispositivo ha una riga in `deliveries`: il "lease" (prestito temporaneo) evita che una
  notifica venga ripetuta mentre la scheda la sta riproducendo; se la scheda non conferma
  entro LEASE_S secondi, la notifica torna disponibile (es. scheda spenta a meta' riproduzione).
"""
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

LEASE_S = 60
TARGET_RE = re.compile(r"^(all|(device|person):[\w.-]{1,64})$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    target      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    source      TEXT NOT NULL,
    dedupe_key  TEXT,
    deliver_at  TEXT NOT NULL,
    expires_at  TEXT,
    created_at  TEXT NOT NULL,
    cancelled   INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_notifications_dedupe
    ON notifications(source, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS deliveries (
    notification_id TEXT NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    device          TEXT NOT NULL,
    lease_until     TEXT,
    acked_at        TEXT,
    PRIMARY KEY (notification_id, device)
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    # Formato fisso in UTC: il confronto tra stringhe in SQL equivale al confronto tra date.
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._db.close()

    def _run(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            self._db.commit()
            return rows

    # --- scrittura ---------------------------------------------------------

    def add(self, *, text: str, target: str, priority: str, source: str,
            deliver_at: datetime, expires_at: datetime | None,
            dedupe_key: str | None) -> tuple[str, bool]:
        """Restituisce (id, creata). Con dedupe_key la stessa coppia (source, key) non si duplica."""
        if dedupe_key:
            found = self._run("SELECT id FROM notifications WHERE source=? AND dedupe_key=?",
                              (source, dedupe_key))
            if found:
                return found[0]["id"], False
        nid = uuid.uuid4().hex
        self._run(
            "INSERT INTO notifications (id, text, target, priority, source, dedupe_key, "
            "deliver_at, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (nid, text, target, priority, source, dedupe_key,
             iso(deliver_at), iso(expires_at) if expires_at else None, iso(utcnow())),
        )
        return nid, True

    def cancel(self, nid: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE notifications SET cancelled=1 WHERE id=?", (nid,))
            self._db.commit()
            return cur.rowcount > 0

    def ack(self, nid: str, device: str) -> bool:
        if not self._run("SELECT 1 FROM notifications WHERE id=?", (nid,)):
            return False
        self._run(
            "INSERT INTO deliveries (notification_id, device, acked_at) VALUES (?,?,?) "
            "ON CONFLICT(notification_id, device) DO UPDATE SET acked_at=excluded.acked_at",
            (nid, device, iso(utcnow())),
        )
        return True

    # --- lettura -----------------------------------------------------------

    def next_for(self, device: str, speaker: str | None = None) -> dict | None:
        """La prossima notifica consegnabile a questo dispositivo, con lease. None se non c'e' nulla."""
        with self._lock:
            now = utcnow()
            now_s = iso(now)
            person = f"person:{speaker.lower()}" if speaker else None
            row = self._db.execute(
                """
                SELECT n.* FROM notifications n
                WHERE n.cancelled = 0
                  AND n.deliver_at <= :now
                  AND (n.expires_at IS NULL OR n.expires_at > :now)
                  AND (n.target = 'all' OR n.target = :dev OR n.target = :person)
                  AND NOT EXISTS (
                      SELECT 1 FROM deliveries d
                      WHERE d.notification_id = n.id AND d.device = :raw
                        AND (d.acked_at IS NOT NULL OR d.lease_until > :now))
                ORDER BY CASE n.priority WHEN 'high' THEN 0 ELSE 1 END, n.deliver_at
                LIMIT 1
                """,
                {"now": now_s, "dev": f"device:{device}", "raw": device, "person": person},
            ).fetchone()
            if row is None:
                return None
            lease = iso(now + timedelta(seconds=LEASE_S))
            self._db.execute(
                "INSERT INTO deliveries (notification_id, device, lease_until) VALUES (?,?,?) "
                "ON CONFLICT(notification_id, device) DO UPDATE SET lease_until=excluded.lease_until",
                (row["id"], device, lease),
            )
            self._db.commit()
            return _to_dict(row)

    def list(self, limit: int = 50) -> list[dict]:
        rows = self._run("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_to_dict(r) for r in rows]


def _to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["cancelled"] = bool(d["cancelled"])
    return d
