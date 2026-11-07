---
type: Component
title: Pipeline dell'agente
description: STT, agente Google ADK, TTS e riconoscimento del parlante nel servizio agent/.
tags: [adk, stt, tts, speaker]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Pipeline

Servizio Python 3.12 (FastAPI + Google ADK) in `agent/`, eseguito in Docker.

1. **Ingresso**: PCM16 LE mono 16 kHz dal [firmware](/firmware/wake-word.md) (`POST /v1/utterance?rate=16000`).
2. **STT** (`stt.py`): ElevenLabs Scribe (`STT_ENGINE=elevenlabs`) con ripiego automatico su faster-whisper locale
   (modello `small`, lingua `it`, `int8`). `STT_COMPARE=1` esegue entrambi per confronto nel log.
3. **Riconoscimento parlante** (`speaker.py`, `enrollment.py`): sherpa-onnx con modello wespeaker, soglia `SPEAKER_THRESHOLD` (0.65).
   Le voci registrate sono dati biometrici, restano nel volume Docker `speaker-data`.
4. **Agente** (`agent.py`): `LlmAgent` ADK via LiteLLM; tool `get_current_time` (fuso `AGENT_TIMEZONE`, default Europe/Rome);
   risposte brevi (`LLM_MAX_TOKENS`, default 160) perché vengono parlate. Sessione per dispositivo in memoria.
5. **TTS** (`tts.py`): ElevenLabs (modello `eleven_flash_v2_5`); senza chiave nessuna risposta vocale.
   L'audio è scaricabile con `GET /v1/reply/{rid}`.
6. **Uscita**: `{"label","transcript","reply"}` più eventuali campi su follow-up e parlante.

Dettagli di rete in [API](/agent/api.md), variabili in [configurazione](/agent/configuration.md).
