---
type: Hardware
title: ESP32-S3 (Waveshare AI Smart Speaker)
description: Caratteristiche verificate con esptool del microcontrollore della scheda.
tags: [esp32-s3, hardware, verificato]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
verified: { by: tool:esptool-5.6.0, at: 2026-11-07T00:00:00Z }
---

# ESP32-S3 (QFN56)

Dati letti dalla scheda il 2026-11-07 con `esptool chip-id` e `flash-id`:

| Voce | Valore |
|---|---|
| Chip | ESP32-S3 (QFN56), revisione v0.2 |
| Core | Dual core a 240 MHz, più core LP |
| Connettività | Wi-Fi, Bluetooth 5 (LE) |
| PSRAM | 8 MB integrata, octal (AP_3v3) |
| Flash | 16 MB, quad, 3.3 V, produttore `0x20`, dispositivo `0x4018` |
| Quarzo | 40 MHz |
| USB | USB-Serial/JTAG nativo |
| MAC | `<MAC-scheda>` |

La flash è usata a 16 MB con [la tabella delle partizioni](/firmware/partitions.md). La PSRAM octal è abilitata in
`sdkconfig.defaults` (vedi [configurazione](/firmware/configuration.md)). Il collegamento al PC è descritto in
[Collegamento USB](/hardware/usb-connection.md).
