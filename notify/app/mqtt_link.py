"""Collegamento MQTT: pubblica le notifiche dovute e riceve le conferme (ack) dalle schede.

Topic:
- jarvis/notify/<dispositivo>  (servizio -> scheda) payload: {"id", "priority"}
- jarvis/ack/<dispositivo>     (scheda -> servizio) payload: {"id"}

Il testo NON va sul broker: la scheda chiede il testo all'agente con l'id
(POST /v1/notifications/{id}/speak), che lo legge dal servizio. Cosi' i promemoria
personali non transitano in chiaro sulla rete MQTT.
"""
import asyncio
import json
import logging
import os

from .store import Store

log = logging.getLogger("notify.mqtt")

TOPIC_NOTIFY = "jarvis/notify/{device}"
TOPIC_ACK = "jarvis/ack/+"


class Link:
    def __init__(self, store: Store, devices: list[str], *, host: str, port: int = 1883,
                 user: str = "", password: str = "", client=None) -> None:
        self.store = store
        self.devices = devices
        self.host, self.port = host, port
        if client is None:
            import paho.mqtt.client as mqtt   # import pigro: i test non hanno bisogno del broker
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jarvis-notify")
            client.username_pw_set(user, password)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
        self.client = client

    # --- callback paho (thread separato) -----------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            client.subscribe(TOPIC_ACK, qos=1)
            log.info("MQTT connesso, ack in ascolto")
        else:
            log.error("MQTT connessione rifiutata: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[0] != "jarvis" or parts[1] != "ack":
            return
        try:
            nid = json.loads(msg.payload)["id"]
        except (ValueError, KeyError, TypeError):
            log.warning("ack non valido da %s", parts[2])
            return
        if self.store.ack(str(nid), parts[2]):
            log.info("ack %s da %s", nid, parts[2])

    # --- pubblicazione -----------------------------------------------------

    def publish_due(self) -> int:
        sent = 0
        for n, dev in self.store.to_publish(self.devices):
            payload = json.dumps({"id": n["id"], "priority": n["priority"]})
            info = self.client.publish(TOPIC_NOTIFY.format(device=dev), payload, qos=1)
            if info.rc == 0:   # se il broker non risponde riproviamo al giro successivo
                self.store.claim(n["id"], dev)
                sent += 1
        return sent

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.publish_due)
            except Exception:
                log.exception("pubblicazione MQTT fallita")
            await asyncio.sleep(1)

    def start(self) -> None:
        if hasattr(self.client, "connect_async"):
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()   # thread di rete: riconnessione automatica

    def stop(self) -> None:
        if hasattr(self.client, "loop_stop"):
            self.client.loop_stop()
            self.client.disconnect()


def from_env(store: Store) -> Link | None:
    host = os.getenv("MQTT_HOST", "").strip()
    if not host:
        return None
    devices = [d.strip() for d in os.getenv("NOTIFY_DEVICES", "").split(",") if d.strip()]
    return Link(store, devices, host=host, port=int(os.getenv("MQTT_PORT", "1883")),
                user=os.getenv("MQTT_USER", "notify"), password=os.getenv("MQTT_PASSWORD", ""))
