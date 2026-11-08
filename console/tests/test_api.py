import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

TOKEN = "console-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

SKILL_MD = "---\nname: prova\ndescription: prova\n---\nIstruzioni.\n"


def zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in entries.items():
            zf.writestr(k, v)
    return buf.getvalue()


class FakeBackend:
    """Sostituisce agente e notify: risposte fisse, registra le chiamate di ricarica."""

    def __init__(self):
        self.reloads = 0
        self.memories = [{"id": "m1", "user_id": "andrea", "kind": "preference", "key": "music.genre",
                          "text": "Ad Andrea piace il jazz.", "status": "active", "pinned": False,
                          "seen_count": 3}]
        self.notifications = [
            {"id": "n1", "target": "person:andrea", "text": "Comprare il latte", "source": "agent",
             "deliver_at": "2026-11-08T18:00:00+00:00", "expires_at": None, "cancelled": False},
            {"id": "n2", "target": "all", "text": "Pipeline finita", "source": "ci",
             "deliver_at": "2026-11-08T18:00:00+00:00", "expires_at": None, "cancelled": False},
        ]

    async def agent(self, method, path, **kw):
        if path == "/v1/speakers":
            return [{"name": "andrea", "samples": 5, "role": "member"}]
        if path == "/v1/memories":
            return self.memories if kw.get("params", {}).get("user") == "andrea" else []
        if path == "/v1/devices":
            return [{"device": "kitchen", "last_seen": 1.0, "last_speaker": "andrea"}]
        if path == "/v1/skills":
            return [{"name": "prova", "type": "instructions", "enabled": True, "problem": None}]
        if path == "/v1/skills/reload":
            self.reloads += 1
            return []
        raise AssertionError(path)

    async def notify(self, method, path, **kw):
        return {"items": self.notifications}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_TOKEN", TOKEN)
    monkeypatch.setenv("CONSOLE_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.delenv("CONSOLE_ALLOW_CODE_SKILLS", raising=False)
    from app import backend, main
    fake = FakeBackend()
    monkeypatch.setattr(backend, "agent", fake.agent)
    monkeypatch.setattr(backend, "notify", fake.notify)
    monkeypatch.setattr(main, "SKILLS_DIR", tmp_path / "skills")
    with TestClient(main.app) as c:
        c.fake = fake
        c.audit_path = tmp_path / "audit.jsonl"
        yield c


def audit_actions(client):
    if not client.audit_path.exists():
        return []
    return [json.loads(l)["action"] for l in client.audit_path.read_text(encoding="utf-8").splitlines()]


def test_index_is_public_but_data_needs_token(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/devices", headers={"Authorization": "Bearer no"}).status_code == 401


def test_devices(client):
    r = client.get("/api/devices", headers=AUTH)
    assert r.json()[0]["device"] == "kitchen"


def test_persons_show_counts_never_text(client):
    body = client.get("/api/persons", headers=AUTH).json()
    assert body[0]["name"] == "andrea"
    assert body[0]["memories"] == {"active": 1}
    assert "Ad Andrea" not in json.dumps(body)


def test_memories_redacted_by_default(client):
    body = client.get("/api/persons/andrea/memories", headers=AUTH).json()
    assert body[0]["text"].startswith("[nascosto")
    assert body[0]["text_len"] == len("Ad Andrea piace il jazz.")
    assert "Ad Andrea" not in json.dumps(body)
    assert audit_actions(client) == []


def test_reveal_memories_is_audited(client):
    body = client.get("/api/persons/andrea/memories?reveal=1", headers=AUTH).json()
    assert body[0]["text"] == "Ad Andrea piace il jazz."
    assert audit_actions(client) == ["rivela_memorie"]
    assert "Ad Andrea" not in client.audit_path.read_text(encoding="utf-8")   # l'audit non contiene il testo


def test_person_notifications_redacted_all_visible(client):
    body = client.get("/api/notifications", headers=AUTH).json()
    by_id = {n["id"]: n for n in body}
    assert by_id["n1"]["text"].startswith("[nascosto")
    assert by_id["n2"]["text"] == "Pipeline finita"


def test_reveal_notifications_is_audited(client):
    body = client.get("/api/notifications?reveal=1", headers=AUTH).json()
    assert {n["text"] for n in body} >= {"Comprare il latte"}
    assert audit_actions(client) == ["rivela_notifiche"]


def test_upload_valid_skill_reloads_agent(client):
    r = client.post("/api/skills/upload?filename=prova.zip", headers={**AUTH, "Content-Type": "application/zip"},
                    content=zip_bytes({"SKILL.md": SKILL_MD}))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "prova"
    assert client.fake.reloads == 1
    assert "skill_caricata" in audit_actions(client)


def test_upload_code_skill_rejected_and_audited(client):
    r = client.post("/api/skills/upload?filename=x.zip", headers={**AUTH, "Content-Type": "application/zip"},
                    content=zip_bytes({"SKILL.md": SKILL_MD, "tools.py": "import os"}))
    assert r.status_code == 422
    assert client.fake.reloads == 0
    assert "skill_rifiutata" in audit_actions(client)


def test_upload_requires_token(client):
    r = client.post("/api/skills/upload?filename=x.zip", headers={"Content-Type": "application/zip"},
                    content=zip_bytes({"SKILL.md": SKILL_MD}))
    assert r.status_code == 401


def test_upload_size_limit(client):
    r = client.post("/api/skills/upload?filename=big.zip", headers={**AUTH, "Content-Type": "application/zip"},
                    content=b"0" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 413


def test_audit_endpoint(client):
    client.get("/api/persons/andrea/memories?reveal=1", headers=AUTH)
    items = client.get("/api/audit", headers=AUTH).json()
    assert items[0]["action"] == "rivela_memorie"


def test_refuses_to_start_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("CONSOLE_TOKEN", raising=False)
    from app import main
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass
