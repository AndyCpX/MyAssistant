---
type: Configuration
title: Tabella delle partizioni
description: Mappa della flash da 16 MB definita in partitions.csv.
tags: [flash, partizioni]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Partizioni (`partitions.csv`)

| Nome | Tipo | Offset | Dimensione |
|---|---|---|---|
| nvs | data/nvs | 0x9000 | 0x6000 |
| phy_init | data/phy | 0xf000 | 0x1000 |
| factory | app | 0x10000 | 0x400000 (4 MB) |
| model | data/spiffs | 0x410000 | 0x500000 (5 MB) |
| storage | data/spiffs | 0x910000 | 0x500000 (5 MB) |

La fine dell'ultima partizione è 0xE10000, dentro i 16 MB della [flash](/hardware/esp32-s3.md).
La partizione `model` contiene i modelli di [wake word](/firmware/wake-word.md).
