---
type: Hardware
title: Pinout Waveshare ESP32-S3-AUDIO-Board
description: Pin I2C, I2S, LED RGB e indirizzi dei componenti audio, da main/board.h.
tags: [pinout, audio, i2s, i2c]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Pinout scheda audio

Definito in `main/board.h`.

| Funzione | GPIO |
|---|---|
| I2C SDA | 11 |
| I2C SCL | 10 |
| I2S MCLK | 12 |
| I2S BCLK | 13 |
| I2S WS | 14 |
| I2S DIN (microfono, ES7210 -> ESP32) | 15 |
| I2S DOUT (speaker, ESP32 -> ES8311) | 16 |
| Anello LED WS2812B (7 LED) | 38 |

## Componenti sul bus I2C
- **ES8311** (codec speaker): indirizzo 8-bit `0x30` (7-bit `0x18`)
- **ES7210** (ADC microfoni): indirizzo 8-bit `0x80` (7-bit `0x40`)
- **TCA9555** (expander IO): indirizzo 7-bit `0x20`; il controllo dell'amplificatore NS4150B è sul port 1 bit 0 (`BOARD_EXIO_PA_CTRL` = 8)

L'audio gira a 16 kHz, I2S in duplex. Il codice è in `audio.c`, vedi [moduli del firmware](/firmware/modules.md).
I colori dell'anello LED sono in [stati LED](/firmware/led-states.md).

## Da completare
Il README segnala come TODO la verifica del pin mapping completo contro lo schema ufficiale Waveshare.
