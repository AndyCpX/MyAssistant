---
type: Design
title: Notifiche, promemoria e timer (servizio notify)
description: Servizio eventi separato dall'agente (notify/) con coda su SQLite, consegna per dispositivo o persona e lease; l'agente lo usa per promemoria e polling della scheda.
tags: [notifiche, promemoria, timer, sqlite, lease]
status: implemented-backend
generated: { by: ai:claude, at: 2026-11-08T00:00:00Z }
---

# Notifiche, promemoria e timer

## Perché un servizio separato
Le sorgenti (CI, Home Assistant, timer) non devono dipendere da LLM, STT o TTS, che stanno nell'agente e si caricano lentamente. I timer devono sopravvivere al rebuild dell'agente. Il servizio è in `notify/` con un proprio volume (`notify-data`) e un proprio token (`NOTIFY_TOKEN`). Non pubblica porte: l'ESP32 parla solo con l'agente.

## Modello
- **Destinatario** (`target`): `all`, `device:<id>` o `person:<nome>` (il nome è normalizzato: minuscolo, spazi sostituiti da `_`).
- **Consegna**: una notifica è consegnabile quando `deliver_at` è passato e non è scaduta o annullata. Ordine: `priority` (high prima), poi `deliver_at`.
- **Lease**: `GET /v1/pending` concede 60 s di prestito per (notifica, dispositivo). Se la scheda non conferma con l'ack (es. spenta durante la riproduzione), la notifica torna disponibile.
- **Ack**: `POST /v1/notifications/{id}/ack?device=…` la chiude per quel dispositivo; per `all` ogni dispositivo la riceve una volta.
- **Deduplica**: `dedupe_key` con `source` evita doppioni (es. retry della CI).

## API del servizio notify (token `Bearer NOTIFY_TOKEN`)
| Metodo | Percorso | Uso |
|---|---|---|
| POST | `/v1/events` | crea notifica o timer (`deliver_at` con fuso obbligatorio) |
| GET | `/v1/pending?device=&speaker=` | prossima notifica con lease |
| POST | `/v1/notifications/{id}/ack?device=` | conferma |
| GET | `/v1/notifications` | elenco per debug |
| DELETE | `/v1/notifications/{id}` | annulla (idempotente) |

## Come lo usa l'agente
- Tool ADK `set_reminder(text, minutes_from_now)`: il destinatario è la persona riconosciuta (`person:`) o, se ignota, il dispositivo. Il contesto della richiesta arriva da un `ContextVar`, come per la memoria.
- Alla risposta vocale di una persona riconosciuta, il primo promemoria pendente viene aggiunto alla risposta e confermato.
- `GET /v1/notifications/next` (polling della scheda, restituisce `audio` come una risposta normale) e `POST /v1/notifications/{id}/ack` sull'agente: da usare dal firmware.

## Stato
- Servizio notify: implementato e coperto da test (17 test di API e coda).
- Agente: tool e integrazione implementati, non ancora provati con Docker e con un modello reale.
- Firmware: stato di polling non ancora implementato (vedi [firmware](/firmware/index.md)).

## Limiti noti
- Notifiche per persona consegnate solo a voce riconosciuta; nessun canale per chi non parla.
- La scheda deve fare polling (latenza di 20–30 s); nessuna spinta in tempo reale.
- Nessun orario di silenzio ancora; da aggiungere lato firmware o servizio.
