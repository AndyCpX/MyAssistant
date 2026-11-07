---
type: Component
title: Wake word JARVIS
description: Rilevamento con esp-sr (AFE a 2 microfoni) e invio dell'audio all'agente.
tags: [esp-sr, wake-word, afe]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Wake word

- Libreria: `espressif/esp-sr` ^2, modello `wn9_jarvis_tts` (`CONFIG_SR_WN_WN9_JARVIS_TTS=y`)
- AFE a 2 microfoni con VAD WebRTC, audio a 16 kHz
- Il modello sta nella partizione `model` ([partizioni](/firmware/partitions.md))
- Codice: `main/wakeword.c`

## Flusso dopo il rilevamento
1. L'anello diventa ciano ([stati LED](/firmware/led-states.md)).
2. `streamer.c` invia l'audio pulito (PCM16 mono 16 kHz) con POST chunked a `/v1/utterance` dell'[agente](/agent/api.md).
3. Lo stream si chiude dopo 500 ms di pausa, oppure dopo 3 s senza parlato o 10 s di durata
   (valori configurabili, vedi [configurazione](/firmware/configuration.md)).
4. La risposta contiene `label`, `transcript` e `reply`; il firmware usa solo `label` per il colore, il resto va nel log seriale.
