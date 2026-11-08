from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"
SRC_TOKEN = "ci-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SRC_AUTH = {"Authorization": f"Bearer {SRC_TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_TOKEN", TOKEN)
    monkeypatch.setenv("NOTIFY_SOURCE_TOKENS", f"ci={SRC_TOKEN}")
    monkeypatch.setenv("NOTIFY_DB", str(tmp_path / "notify.db"))
    monkeypatch.delenv("MQTT_HOST", raising=False)
    from app import main
    main.limiter.limit = 1000
    main.limiter._hits.clear()
    with TestClient(main.app) as c:
        yield c


def post(client, headers=AUTH, **body):
    body.setdefault("text", "ciao")
    return client.post("/v1/events", json=body, headers=headers)


def pending(client, device="kitchen", speaker="andrea"):
    r = client.get("/v1/pending", params={"device": device, "speaker": speaker}, headers=AUTH)
    assert r.status_code == 200
    return r.json()["notification"]


# --- API ----------------------------------------------------------------

def test_healthz_is_open(client):
    assert client.get("/healthz").status_code == 204


def test_agent_routes_require_token(client):
    assert client.get("/v1/pending", params={"device": "d", "speaker": "a"}).status_code == 401
    assert client.get("/v1/notifications").status_code == 401
    assert client.get("/v1/notifications/x").status_code == 401
    assert client.post("/v1/notifications/x/ack", params={"device": "d"}).status_code == 401


def test_source_token_can_post_but_not_read(client):
    assert post(client, headers=SRC_AUTH, text="build ok").status_code == 201
    assert client.get("/v1/notifications", headers=SRC_AUTH).status_code == 401


def test_unknown_token_cannot_post(client):
    r = post(client, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_source_name_comes_from_token_not_body(client):
    nid = post(client, headers=SRC_AUTH, source="agent", text="x").json()["id"]
    assert client.get(f"/v1/notifications/{nid}", headers=AUTH).json()["source"] == "ci"


def test_rate_limit_per_source(client):
    from app import main
    main.limiter.limit = 2
    assert post(client, headers=SRC_AUTH).status_code == 201
    assert post(client, headers=SRC_AUTH).status_code == 201
    assert post(client, headers=SRC_AUTH).status_code == 429
    assert post(client).status_code == 201   # l'agente ha il suo contatore


def test_dedupe_key_prevents_duplicates(client):
    a = post(client, headers=SRC_AUTH, text="build ok", dedupe_key="run-42").json()
    b = post(client, headers=SRC_AUTH, text="build ok", dedupe_key="run-42").json()
    assert a["id"] == b["id"] and b["status"] == "duplicate"


def test_validation(client):
    assert post(client, text="   ").status_code == 422
    assert post(client, target="kitchen").status_code == 422
    assert post(client, target="device:").status_code == 422
    assert post(client, deliver_at="2026-11-08T18:00:00").status_code == 422   # senza fuso
    assert post(client, text="x" * 501).status_code == 422


def test_expires_before_deliver_is_rejected(client):
    now = datetime.now(timezone.utc)
    r = post(client, deliver_at=(now + timedelta(hours=2)).isoformat(),
             expires_at=(now + timedelta(hours=1)).isoformat())
    assert r.status_code == 422


def test_cancel_is_idempotent_and_hides_notification(client):
    nid = post(client).json()["id"]
    assert client.delete(f"/v1/notifications/{nid}", headers=AUTH).status_code == 204
    assert client.delete(f"/v1/notifications/{nid}", headers=AUTH).status_code == 204
    assert client.get(f"/v1/notifications/{nid}", headers=AUTH).status_code == 404
    assert client.delete("/v1/notifications/inesistente", headers=AUTH).status_code == 404


def test_refuses_to_start_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIFY_TOKEN", raising=False)
    monkeypatch.setenv("NOTIFY_DB", str(tmp_path / "x.db"))
    from app import main
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass


# --- promemoria personali (pull dall'agente) ------------------------------

def test_person_reminder_only_for_that_speaker(client):
    post(client, text="comprare il latte", target="person:Andrea")
    assert pending(client, speaker="Marta") is None
    assert pending(client, speaker="andrea")["text"] == "comprare il latte"


def test_person_reminder_leased_then_acked(client, monkeypatch):
    import app.store as st
    monkeypatch.setattr(st, "LEASE_S", 0)
    post(client, text="latte", target="person:andrea")
    assert pending(client)["text"] == "latte"
    assert pending(client)["text"] == "latte"          # lease scaduto: riproposto
    nid = pending(client)["id"]
    assert client.post(f"/v1/notifications/{nid}/ack", params={"device": "kitchen"},
                       headers=AUTH).status_code == 204
    assert pending(client) is None


def test_device_targets_are_not_served_by_pending(client):
    post(client, text="a tutti", target="all")
    post(client, text="solo cucina", target="device:kitchen")
    assert pending(client) is None   # le notifiche per dispositivo passano da MQTT


def test_future_person_reminder_waits(client):
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    post(client, text="dopo", target="person:andrea", deliver_at=later)
    assert pending(client) is None


def test_expired_notification_is_not_delivered(client):
    from app import main
    from datetime import datetime as dt
    main.store.add(text="vecchia", target="person:andrea", priority="normal", source="t",
                   deliver_at=dt.now(timezone.utc) - timedelta(hours=2),
                   expires_at=dt.now(timezone.utc) - timedelta(hours=1), dedupe_key=None)
    assert pending(client) is None


def test_high_priority_first(client):
    post(client, text="normale", target="person:andrea")
    post(client, text="urgente", target="person:andrea", priority="high")
    assert pending(client)["text"] == "urgente"
