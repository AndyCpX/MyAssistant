---
type: Hardware
title: Collegamento USB e esptool
description: Come la scheda appare su Windows e come interrogarla con esptool.
tags: [usb, com3, esptool, windows]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
verified: { by: tool:esptool-5.6.0, at: 2026-11-07T00:00:00Z }
---

# Collegamento USB

- Porta seriale: **COM3**, mostrata da Windows come "USB Serial Device"
- Identificativi: VID `303A`, PID `1001` (USB Serial/JTAG integrato di Espressif, nessun chip bridge esterno)
- Numero di serie del dispositivo: il MAC `<MAC-scheda>`

## esptool
`esptool` non è nel PATH e il `python` del PATH (ESP-IDF) non ha il modulo. Usare l'eseguibile dell'installazione ESP-IDF
(v5.6.0, comandi con trattini):

```powershell
C:\Espressif\tools\python\v6.1\venv\Scripts\esptool.exe --port COM3 chip-id
C:\Espressif\tools\python\v6.1\venv\Scripts\esptool.exe --port COM3 flash-id
```

A fine comando la scheda viene riavviata con un reset hardware (RTS).

## Download mode
Tenere premuto BOOT e premere RESET.

Se la scheda non compare, vedi [cavo senza dati](/troubleshooting/cable-no-data.md).
