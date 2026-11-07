---
type: Reference
title: Stati dell'anello LED
description: Significato dei colori dell'anello WS2812B a 7 LED.
tags: [led, ux]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Stati LED

Implementati in `main/main.c` (LED su GPIO 38, vedi [pinout](/hardware/audio-board-pinout.md)).

| Colore | Significato |
|---|---|
| Blu | avvio |
| Verde tenue | in ascolto della wake word |
| Ciano | wake word rilevata / streaming in corso |
| Verde | risposta con label `positive` |
| Bianco | risposta con label `neutral` (o label sconosciuta) |
| Rosso | risposta con label `negative` |
| Arancione | errore di rete o del servizio |
| Rosso fisso | errore di init audio o wake word (il firmware si ferma) |

I colori verde/bianco/rosso restano 2,5 s. Se non arriva un risultato entro 15 s il firmware torna in ascolto.
L'etichetta arriva dal campo `label` dell'[API dell'agente](/agent/api.md).
