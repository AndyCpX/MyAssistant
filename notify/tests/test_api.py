import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_TOKEN", TOKEN)
    monkeypatch.setenv("NOTIFY_DB", str(tmp_path / "notify.db"))
    from app import main
    with TestClient(main.app) as c:
        yield c


def post(client, **body):
    body.setdefault("text", "ciao")
    return client.post("/v1/events", json=body, headers=AUTH)


def pending(client, device="kitchen", speaker=None):
    params = {"device": device}
    if speaker:
        params["speaker"] = speaker
    r = client.get("/v1/pending", params=params, headers=AUTH)
    assert r.status_code == 200
    return r.json()["notification"]


def test_healthz_is_open(client):
    assert client.get("/healthz").status_code == 204


def test_routes_require_token(client):
    assert client.post("/v1/events", json={"text": "x"}).status_code == 401
    assert client.get("/v1/pending", params={"device": "d"}).status_code == 401
    assert client.get("/v1/pending", params={"device": "d"},
                      headers={"Authorization": "Bearer sbagliato"}).status_code == 401


def test_create_and_deliver_to_all(client):
    r = post(client, text="La pipeline e' finita", source="ci")
    assert r.status_code == 201 and r.json()["status"] == "created"
    n = pending(client, device="kitchen")
    assert n["text"] == "La pipeline e' finita"
    assert n["target"] == "all"


def test_broadcast_reaches_every_device_once_each(client):
    post(client, text="a tutti")
    assert pending(client, "kitchen")["text"] == "a tutti"
    assert pending(client, "bedroom")["text"] == "a tutti"
    nid = pending(client, "kitchen")  # gia' in lease: nessuna ripetizione
    assert nid is None


def test_ack_removes_notification_for_that_device(client):
    r = post(client, text="uno")
    nid = r.json()["id"]
    assert pending(client, "kitchen")["id"] == nid
    assert client.post(f"/v1/notifications/{nid}/ack", params={"device": "kitchen"},
                       headers=AUTH).status_code == 204
    assert pending(client, "kitchen") is None


def test_lease_expiry_redelivers_if_not_acked(client, monkeypatch):
    import app.store as st
    monkeypatch.setattr(st, "LEASE_S", 0)
    post(client, text="riprova")
    assert pending(client, "kitchen")["text"] == "riprova"
    # lease scaduto subito (LEASE_S=0): la scheda che si e' spenta la riceve di nuovo
    assert pending(client, "kitchen")["text"] == "riprova"


def test_device_target_only_for_that_device(client):
    post(client, text="solo cucina", target="device:kitchen")
    assert pending(client, "bedroom") is None
    assert pending(client, "kitchen")["text"] == "solo cucina"


def test_person_target_needs_recognised_speaker(client):
    post(client, text="comprare il latte", target="person:Andrea")
    assert pending(client, "kitchen") is None                      # nessuno riconosciuto
    assert pending(client, "kitchen", speaker="Marta") is None     # altra persona
    assert pending(client, "kitchen", speaker="andrea")["text"] == "comprare il latte"


def test_future_notification_waits_for_deliver_at(client):
    from datetime import datetime, timezone
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    post(client, text="timer", deliver_at=later)
    assert pending(client) is None


def test_expires_before_deliver_is_rejected(client):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    r = post(client, text="scaduta in partenza",
             deliver_at=(now + timedelta(hours=2)).isoformat(),
             expires_at=(now + timedelta(hours=1)).isoformat())
    assert r.status_code == 422


def test_expired_notification_is_not_delivered(client):
    from datetime import datetime, timezone
    from app import main
    nid, _ = main.store.add(text="vecchia", target="all", priority="normal", source="t",
                            deliver_at=datetime.now(timezone.utc) - timedelta(hours=2),
                            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                            dedupe_key=None)
    assert pending(client) is None


def test_high_priority_first(client):
    post(client, text="normale")
    post(client, text="urgente", priority="high")
    assert pending(client, "kitchen")["text"] == "urgente"
    assert pending(client, "kitchen")["text"] == "normale"


def test_dedupe_key_prevents_duplicates(client):
    a = post(client, text="build ok", source="ci", dedupe_key="run-42").json()
    b = post(client, text="build ok", source="ci", dedupe_key="run-42").json()
    assert a["id"] == b["id"] and b["status"] == "duplicate"
    # stessa chiave ma altra sorgente: evento diverso
    c = post(client, text="altro", source="ha", dedupe_key="run-42").json()
    assert c["id"] != a["id"]


def test_cancel_stops_delivery(client):
    nid = post(client, text="annullami").json()["id"]
    assert client.delete(f"/v1/notifications/{nid}", headers=AUTH).status_code == 204
    assert pending(client) is None
    # DELETE idempotente: ripetere l'annullamento non e' un errore
    assert client.delete(f"/v1/notifications/{nid}", headers=AUTH).status_code == 204
    assert client.delete("/v1/notifications/inesistente", headers=AUTH).status_code == 404


def test_validation(client):
    assert post(client, text="   ").status_code == 422
    assert post(client, text="x", target="kitchen").status_code == 422
    assert post(client, text="x", target="device:").status_code == 422
    assert post(client, text="x", deliver_at="2026-11-08T18:00:00").status_code == 422  # senza fuso
    assert post(client, text="x" * 501).status_code == 422


def test_ack_unknown_id(client):
    assert client.post("/v1/notifications/nope/ack", params={"device": "k"},
                       headers=AUTH).status_code == 404


def test_refuses_to_start_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIFY_TOKEN", raising=False)
    monkeypatch.setenv("NOTIFY_DB", str(tmp_path / "x.db"))
    from app import main
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass
