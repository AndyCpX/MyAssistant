---
type: Configuration
title: Configurazione del firmware
description: sdkconfig.defaults, sdkconfig.local e le opzioni del menu Smart Speaker.
tags: [sdkconfig, kconfig, wifi]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Configurazione

## sdkconfig.defaults (versionato)
- Target `esp32s3`, flash 16 MB, modo QIO a 80 MHz
- PSRAM abilitata, modo octal, 80 MHz
- CPU a 240 MHz, `FREERTOS_HZ=1000`
- Partizioni custom: `partitions.csv` (vedi [partizioni](/firmware/partitions.md))
- Wake word: `CONFIG_SR_WN_WN9_JARVIS_TTS=y` (vedi [wake word](/firmware/wake-word.md))
- Rete: finestre TCP da 32 KB e buffer Wi-Fi maggiorati per l'upload audio

## sdkconfig.local (non versionato)
Copiare `sdkconfig.local.example` in `sdkconfig.local` e impostare Wi-Fi e URL del servizio, poi:

```powershell
del sdkconfig
idf.py reconfigure
```

Chiavi: `CONFIG_SS_WIFI_SSID`, `CONFIG_SS_WIFI_PASSWORD`, `CONFIG_SS_SENTIMENT_URL`
(es. `http://<ip-host>:8080/v1/utterance`), `CONFIG_SS_AUTH_TOKEN` (uguale a `AGENT_TOKEN` dell'[agente](/agent/configuration.md)).
SSID vuoto = Wi-Fi e streaming disattivati, la wake word funziona comunque.

## Menu "Smart Speaker" (`main/Kconfig.projbuild`)
| Opzione | Default | Note |
|---|---|---|
| `SS_VOLUME` | 70 | 0-100; valori alti saturano l'amplificatore e distorcono |
| `SS_END_SILENCE_MS` | 500 | pausa che chiude lo stream |
| `SS_WAIT_SPEECH_MS` | 5000 | attesa massima del parlato dopo la wake word |
| `SS_MAX_UTTERANCE_MS` | 10000 | durata massima dello stream |
