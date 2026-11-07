---
type: Reference
title: Moduli del firmware
description: Elenco dei file sorgente in main/ e delle rispettive responsabilità.
tags: [codice, struttura]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Moduli (`main/`)

| File | Ruolo |
|---|---|
| `main.c` | `app_main`: init LED, rete, audio, wake word; ciclo di stato e colori ([LED](/firmware/led-states.md)) |
| `board.h` | pin e indirizzi ([pinout](/hardware/audio-board-pinout.md)) |
| `audio.c/.h` | I2C, TCA9555 (amplificatore), I2S duplex, ES8311 e ES7210, 16 kHz |
| `wakeword.c/.h` | AFE e rilevamento ([wake word](/firmware/wake-word.md)) |
| `streamer.c/.h` | POST chunked dell'audio all'agente e parsing della risposta |
| `net.c/.h` | connessione Wi-Fi |
| `player.c/.h` | riproduzione della risposta audio |
| `Kconfig.projbuild` | opzioni del menu Smart Speaker ([configurazione](/firmware/configuration.md)) |

Il boot esegue anche un test audio: tono a 440 Hz, poi 1 s di registrazione con livello RMS.
Wi-Fi e streaming sono opzionali: se `net_init` o `streamer_init` falliscono, la wake word funziona comunque.
