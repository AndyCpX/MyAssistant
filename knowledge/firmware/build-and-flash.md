---
type: Procedure
title: Build e flash del firmware
description: Toolchain ESP-IDF v6.1 e comandi per compilare e flashare su COM3.
tags: [esp-idf, build, flash]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Build e flash

## Toolchain
- ESP-IDF v6.1 installato in `C:\Espressif` (richiesto >= 5.3)
- Aprire "ESP-IDF PowerShell", oppure caricare `C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1`
- `.vscode/settings.json` punta a `C:\esp\v6.1\esp-idf`

## Comandi
```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COM3 flash monitor
```

## Note
- `managed_components/` è generato dal registry (`espressif/led_strip`, `esp_codec_dev`, `esp-sr`) e non va modificato.
- `sdkconfig` è generato; per rigenerarlo dopo aver cambiato `sdkconfig.local` vedi [configurazione](/firmware/configuration.md).
- Se la scheda non risponde: [collegamento USB](/hardware/usb-connection.md) e [troubleshooting](/troubleshooting/cable-no-data.md).
