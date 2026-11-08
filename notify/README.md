# notify — servizio eventi e promemoria di JARVIS

Servizio separato dall'agente: riceve eventi (CI, Home Assistant, timer), li conserva in SQLite
e li consegna a un dispositivo o a una persona riconosciuta. Dettagli di design in
`knowledge/agent/notifications.md`.

## Avvio
Il servizio è nel compose dell'agente (`agent/docker-compose.yml`). Serve `NOTIFY_TOKEN` in `agent/.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Locale, senza Docker:

```bash
pip install -r requirements.txt -r requirements-dev.txt
NOTIFY_TOKEN=prova NOTIFY_DB=./notify.db uvicorn app.main:app --port 8081
pytest
```

## Esempi

```bash
# notifica per tutti (es. da una GitHub Action)
curl -X POST http://localhost:8081/v1/events -H "Authorization: Bearer $NOTIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"La pipeline è finita, il codice è su dev","source":"ci","dedupe_key":"run-42"}'

# timer per una persona, tra 10 minuti (il fuso orario è obbligatorio)
curl -X POST http://localhost:8081/v1/events -H "Authorization: Bearer $NOTIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"Il tuo timer è scaduto","target":"person:andrea","deliver_at":"2026-11-08T18:10:00+01:00"}'
```

## Regole
- `target`: `all`, `device:<id>`, `person:<nome>`.
- Una scheda riceve una notifica alla volta e la conferma con l'ack; senza ack, dopo 60 s la notifica torna disponibile.
- `dedupe_key` + `source` identificano un evento: ripeterlo non crea un duplicato.
- Il servizio non parla con l'ESP32: la consegna passa dall'agente.
