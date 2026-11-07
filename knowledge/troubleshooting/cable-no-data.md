---
type: Troubleshooting
title: Scheda non rilevata da Windows (cavo senza dati)
description: Nessuna porta COM e nessun dispositivo VID 303A: la causa era il cavo USB.
tags: [usb, cavo, windows]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
verified: { by: human:andyc, at: 2026-11-07T00:00:00Z }
---

# Scheda non rilevata

## Sintomo
`[System.IO.Ports.SerialPort]::GetPortNames()` restituisce un elenco vuoto e tra i dispositivi USB non c'è nulla di
Espressif (VID `303A`), nemmeno come "dispositivo sconosciuto". Ricollegare lo stesso cavo non cambia nulla.

## Causa
Cavo USB di sola ricarica, senza le linee dati.

## Soluzione
Usare un cavo che trasferisce dati. Subito dopo la scheda è comparsa come COM3 ([collegamento USB](/hardware/usb-connection.md)).

## Se capita ancora
1. Provare un'altra porta USB direttamente sul PC, non su hub o dock.
2. Controllare il LED di alimentazione della scheda.
3. Entrare in download mode (BOOT premuto, poi RESET).
4. Provare la scheda su un altro PC.

Controllo da PowerShell:
```powershell
[System.IO.Ports.SerialPort]::GetPortNames()
Get-PnpDevice -PresentOnly -Class USB,Ports | Select Status,FriendlyName,InstanceId
```
