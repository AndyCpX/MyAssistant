---
type: Design
title: Notifiche, promemoria e timer (servizio notify + MQTT)
description: Servizio eventi separato dall'agente (notify/) con coda SQLite; le notifiche per scheda arrivano via MQTT (Mosquitto), i promemoria personali via agente quando la persona parla.
tags: [notifiche, promemoria, timer, sqlite, mqtt, lease]
status: implemented-backend
generated: { by: ai:claude, at: 2026-11-08T00:00:00Z }
---

# Notifiche, promemoria e timer

## Perché un servizio separato
Le sorgenti (CI, Home Assistant, timer) non devono dipendere da LLM, STT o TTS, che stanno nell'agente e si caricano lentamente. I timer devono sopravvivere al rebuild dell'agente. Il servizio è in `notify/` con un proprio volume (`notify-data`). Non è raggiungibile dalla LAN: le schede non gli parlano direttamente.

## Percorsi di consegna
- **Notifiche per scheda** (`all`, `device:<id>`): il servizio pubblica su MQTT `jarvis/notify/<id>` un messaggio `{id, priority}`. La scheda conferma su `jarvis/ack/<id>` dopo la riproduzione. Il testo non va sul broker: la scheda lo chiede all'agente con `POST /v1/notifications/{id}/speak`.
- **Promemoria personali** (`person:<nome>`): non passano da MQTT. Vengono aggiunti alla risposta vocale quando la persona riconosciuta parla con la scheda. La conferma arriva quando la scheda scarica l'audio di quella risposta (`GET /v1/reply/{rid}`).

Dettagli del broker, utenti e ruoli: [mosquitto/README.md](/agent/mosquitto/README.md) nel repo.

## Modello
- **Destinatario** (`target`): `all`, `device:<id>` o `person:<nome>` (il nome è normalizzato: minuscolo, spazi sostituiti da `_`). `all` va solo ai dispositivi in `NOTIFY_DEVICES`.
- **Consegna**: una notifica è consegnabile quando `deliver_at` è passato e non è scaduta o annullata. Ordine: `priority` (high prima), poi `deliver_at`.
- **Lease**: dopo ogni pubblicazione (o consegna di un promemoria) la coppia (notifica, dispositivo) ha 60 s di prestito. Senza conferma entro il lease, la notifica viene ripubblicata: così una scheda spenta non fa perdere nulla.
- **Ack**: chiude la coppia (notifica, dispositivo); non viene più ripubblicata.
- **Deduplica**: `dedupe_key` con `source` evita doppioni (es. retry della CI).
- **Limiti**: 30 eventi al minuto per sorgente (`NOTIFY_RATE_PER_MIN`); testo max 500 caratteri.

## Sorgenti e token
- `NOTIFY_TOKEN`: agente (lettura, promemoria personali, ack, speak). Accesso completo.
- `NOTIFY_SOURCE_TOKENS=ci=<token>,ha=<token>`: sorgenti che possono solo creare eventi. La sorgente è quella associata al token, non quella dichiarata nel corpo.

## API del servizio notify
| Metodo | Percorso | Chi | Uso |
|---|---|---|---|
| POST | `/v1/events` | sorgenti, agente | crea notifica o timer (`deliver_at` con fuso obbligatorio) |
| GET | `/v1/pending?device=&speaker=` | agente | promemoria della persona, con lease |
| GET | `/v1/notifications/{id}` | agente | testo di una notifica (per lo speak) |
| POST | `/v1/notifications/{id}/ack?device=` | agente | conferma di un promemoria personale |
| GET | `/v1/notifications` | operatore | elenco per debug |
| DELETE | `/v1/notifications/{id}` | operatore | annulla (idempotente) |

## Broker MQTT
- Mosquitto 2 nel compose, porta 1883 sulla LAN, senza anonimi.
- Plugin `dynamic-security`, default deny. Ogni scheda ha un ruolo con solo `jarvis/notify/<id>` (lettura) e `jarvis/ack/<id>` (scrittura).
- Verificato: scheda senza permesso negata su altri topic e su pubblicazioni altrui; anonimi rifiutati; consegna e ack end-to-end nello stack compose.
- Il file delle ACL (`acl`) è stato abbandonato: con Mosquitto il default era «consenti».

## Come lo usa l'agente
- Tool ADK `set_reminder(text, minutes_from_now)`: il destinatario è la persona riconosciuta (`person:`) o, se ignota, il dispositivo. Il contesto della richiesta arriva da un `ContextVar`, come per la memoria.
- Endpoint `POST /v1/notifications/{id}/speak`: restituisce `audio` come una risposta normale, solo se la notifica è destinata a quel dispositivo (`X-Device-Id`).

## Stato
- Servizio notify: implementato, 27 test (API, coda, MQTT con client finto).
- Broker: verificato nello stack compose con schede simulate (paho).
- Agente: tool, speak e promemoria personali implementati; non ancora provati con il modello reale né con il container dell'agente aggiornato.
- Firmware: implementato in `main/notify.c` (client `espressif/mqtt`, coda da 4 id, richiesta `speak`, riproduzione con `player_play_path`, conferma su `jarvis/ack/<id>`). Verificato su hardware (COM3): notifica ricevuta, testo e audio scaricati dall'agente (2,6 s di audio), conferma registrata dal servizio.
- Configurazione scheda: `SS_DEVICE_ID`, `SS_MQTT_URI`, `SS_MQTT_PASSWORD` (sdkconfig.local, non versionato). Senza `SS_MQTT_URI` le notifiche restano disattivate e la scheda funziona come prima.

## Limiti noti
- Notifiche per persona consegnate solo a voce riconosciuta; nessun canale per chi non parla.
- Il traffico MQTT è in chiaro sulla LAN (nessun TLS): accettabile finché il broker non esce dalla LAN.
- Nessun orario di silenzio; da aggiungere lato servizio o firmware.
- Il promemoria personale senza TTS attivo non viene confermato: il lease lo ripropone.
