---
type: API
title: API HTTP dell'agente
description: Endpoint esposti sulla porta 8080 dal servizio agent/.
tags: [api, fastapi, http]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# API (porta 8080)

| Metodo | Percorso | Funzione |
|---|---|---|
| GET | `/healthz` | health check (204) |
| POST | `/v1/utterance?rate=16000` | audio PCM16 LE mono (anche chunked) -> `{"label","transcript","reply"}` |
| POST | `/v1/text` | `{"text": "..."}` -> risposta senza audio, per test |
| GET | `/v1/reply/{rid}` | audio della risposta sintetizzata |
| GET | `/v1/speakers` | elenco dei parlanti registrati |
| POST | `/v1/speakers/{name}/rename?to=...` | rinomina un parlante |
| DELETE | `/v1/speakers/{name}` | elimina un parlante |

## Autenticazione e sessioni
- Con `AGENT_TOKEN` impostato serve il Bearer token; nel firmware è `CONFIG_SS_AUTH_TOKEN` ([configurazione](/firmware/configuration.md)).
- Header `X-Device-Id` identifica il dispositivo per la sessione; se manca si usa l'IP.

## Test senza ESP32
```powershell
curl.exe -X POST localhost:8080/v1/text -H "Content-Type: application/json" -d "{\"text\":\"che ore sono?\"}"
curl.exe -X POST "localhost:8080/v1/utterance?rate=16000" -H "Transfer-Encoding: chunked" --data-binary "@frase.pcm"
```

Endpoint per notifiche (vedi [notifiche](/agent/notifications.md)): `POST /v1/notifications/{id}/speak` (la scheda chiede il testo di una notifica ricevuta via MQTT e riceve l'audio; header `X-Device-Id`). La conferma delle notifiche per scheda avviene via MQTT, non via HTTP.

Flusso interno in [pipeline](/agent/pipeline.md).
