---
type: Configuration
title: Configurazione dell'agente
description: Docker Compose e variabili d'ambiente di agent/.env.
tags: [docker, env, llm]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Configurazione

## Avvio
```powershell
cd agent
copy .env.example .env
docker compose up --build
```
`agent/.env` contiene chiavi API e non è versionato: non va stampato né committato.

## Docker
Un servizio `agent` sulla porta 8080, `restart: unless-stopped`, due volumi:
- `whisper-models`: cache del modello STT (`/models/hf`)
- `speaker-data`: voci registrate (`/data`), dati biometrici solo locali

L'immagine scarica il modello speaker wespeaker al build ed espone un healthcheck su `/healthz`.

## Variabili principali
| Variabile | Uso |
|---|---|
| `LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY` | qualsiasi modello LiteLLM (default Ollama Cloud) |
| `LLM_THINK=false` | niente ragionamento nella risposta: più pulita e veloce per la voce |
| `STT_ENGINE`, `STT_MODEL`, `STT_LANGUAGE`, `STT_COMPUTE_TYPE`, `STT_COMPARE`, `STT_PROMPT` | riconoscimento vocale |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL` | sintesi vocale |
| `SPEAKER_THRESHOLD` | similarità minima 0-1 per riconoscere un parlante |
| `AGENT_TOKEN`, `AGENT_LANGUAGE`, `AGENT_TIMEZONE` | accesso, lingua delle risposte, fuso orario |

Il firmware punta all'agente tramite l'URL in `sdkconfig.local` ([firmware](/firmware/configuration.md)).
