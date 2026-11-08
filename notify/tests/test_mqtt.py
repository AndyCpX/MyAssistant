import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import mqtt_link, store as st
from app.store import Store


class FakeClient:
    """Sostituisce paho: registra le pubblicazioni, senza broker."""

    def __init__(self, rc: int = 0) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.rc = rc

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, json.loads(payload)))
        return SimpleNamespace(rc=self.rc)

    def subscribe(self, *args, **kwargs):
        pass


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "q.db"))
    yield s
    s.close()


def add(store, text="ciao", target="all", deliver_in=timedelta(0), expires_in=None,
        priority="normal", dedupe=None):
    now = datetime.now(timezone.utc)
    nid, _ = store.add(text=text, target=target, priority=priority, source="t",
                       deliver_at=now + deliver_in,
                       expires_at=(now + expires_in) if expires_in else None,
                       dedupe_key=dedupe)
    return nid


DEVICES = ["kitchen", "bedroom"]


def test_all_fans_out_to_configured_devices(store):
    nid = add(store, target="all")
    pairs = store.to_publish(DEVICES)
    assert sorted(d for n, d in pairs if n["id"] == nid) == ["bedroom", "kitchen"]


def test_unknown_device_gets_nothing(store):
    add(store, target="device:garage")
    assert store.to_publish(DEVICES) == []


def test_device_target_only_that_device(store):
    add(store, target="device:kitchen")
    assert [d for _, d in store.to_publish(DEVICES)] == ["kitchen"]


def test_person_targets_never_go_to_mqtt(store):
    add(store, target="person:andrea")
    assert store.to_publish(DEVICES) == []


def test_future_and_expired_are_not_published(store):
    add(store, target="all", deliver_in=timedelta(hours=1))
    add(store, target="all", deliver_in=timedelta(hours=-2), expires_in=timedelta(hours=-1))
    assert store.to_publish(DEVICES) == []


def test_publish_then_lease_then_ack(store, monkeypatch):
    link = mqtt_link.Link(store, DEVICES, host="x", client=FakeClient())
    nid = add(store, target="all")
    assert link.publish_due() == 2
    assert link.client.sent[0][0] in ("jarvis/notify/kitchen", "jarvis/notify/bedroom")
    assert link.client.sent[0][1] == {"id": nid, "priority": "normal"}   # niente testo sul broker
    assert link.publish_due() == 0                                       # lease attivo: nessun doppione

    class Msg:
        topic = "jarvis/ack/kitchen"
        payload = json.dumps({"id": nid}).encode()
    link._on_message(None, None, Msg)
    # scadiamo tutti i lease: se la cucina non avesse confermato verrebbe ripubblicata
    store._run("UPDATE deliveries SET lease_until='2000-01-01T00:00:00+00:00'")
    assert [d for _, d in store.to_publish(DEVICES)] == ["bedroom"]   # la cucina ha confermato


def test_lease_expiry_republishes(store, monkeypatch):
    monkeypatch.setattr(st, "LEASE_S", 0)
    link = mqtt_link.Link(store, ["kitchen"], host="x", client=FakeClient())
    add(store, target="device:kitchen")
    assert link.publish_due() == 1
    assert link.publish_due() == 1   # nessun ack: riprovato


def test_broker_error_does_not_claim(store):
    link = mqtt_link.Link(store, ["kitchen"], host="x", client=FakeClient(rc=4))
    add(store, target="device:kitchen")
    assert link.publish_due() == 0
    assert [d for _, d in store.to_publish(["kitchen"])] == ["kitchen"]   # riproverà


def test_bad_ack_is_ignored(store):
    link = mqtt_link.Link(store, ["kitchen"], host="x", client=FakeClient())
    nid = add(store, target="device:kitchen")

    class Bad:
        topic = "jarvis/ack/kitchen"
        payload = b"non json"
    class Other:
        topic = "altro/topic"
        payload = json.dumps({"id": nid}).encode()
    link._on_message(None, None, Bad)
    link._on_message(None, None, Other)
    assert [d for _, d in store.to_publish(["kitchen"])] == ["kitchen"]


def test_from_env_disabled_without_host(store, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    assert mqtt_link.from_env(store) is None
