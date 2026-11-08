---
type: Design
title: Console di diagnostica (servizio console)
description: Servizio Python separato per ispezionare dispositivi, persone, memorie e notifiche e per caricare una skill da zip, con redazione dei dati personali e audit.
tags: [console, diagnostica, memorie, skill, audit, sicurezza]
status: implemented-mvp
generated: { by: ai:claude, at: 2026-11-08T00:00:00Z }
---

# Console di diagnostica

## Scopo
Capire perché JARVIS ha fatto una cosa: quali memorie ha, cosa è in coda, quali skill sono caricate, quali schede hanno parlato con l'agente. Uso personale, in locale.

## Architettura
- Servizio `console/` (FastAPI) con interfaccia HTML/JavaScript senza build: nessuna dipendenza da Node.
- Non accede a Qdrant né ai file di `speaker-data`: legge solo le API di [agente](/agent/api.md) (`/v1/speakers`, `/v1/memories`, `/v1/skills`, `/v1/devices`) e del servizio notify.
- Porta pubblicata solo su `127.0.0.1:8090`. Accesso con `CONSOLE_TOKEN` (obbligatorio all'avvio).

## Redazione dei dati personali
- Il testo delle memorie e dei promemoria personali è nascosto di default; è mostrato solo con `?reveal=1`.
- Ogni rivelazione finisce nell'audit (`rivela_memorie`, `rivela_notifiche`) con persona e numero di elementi, mai il contenuto.
- L'elenco delle persone mostra solo conteggi per stato, nessun testo e nessuna voce.
- L'access log di uvicorn è disattivato: i percorsi contengono nomi.

## Caricamento skill da zip
Controlli prima di scrivere: dimensione (5 MB), numero di file (200), dimensione scompressa (20 MB), rapporto di compressione (≤ 100), percorsi sicuri, niente link simbolici, niente file di codice, solo tipi `instructions` e `http`, nessun blocco `commands`, nessuna sovrascrittura. Poi ricarica dell'agente.

Motivo: una skill con `tools.py`, `commands` o script eseguirebbe programmi nel container dell'agente. Sono rifiutate salvo `CONSOLE_ALLOW_CODE_SKILLS=1`.

## Limiti noti
- "Dispositivi attivi" = ultima interazione dall'ultimo riavvio dell'agente. Non è un heartbeat: serve un messaggio periodico dal firmware.
- Nessuna paginazione: con molte persone le chiamate all'agente crescono di una per persona.
- Non si possono eliminare o modificare memorie dalla console (sola lettura, tranne il caricamento skill).
- Il caricamento scrive nella cartella `agent/skills`, montata in lettura e scrittura solo nella console.

## Test
33 test (zip malevoli, redazione, audit, auth) e verifica sul container con l'agente reale: persone e conteggi corretti, memorie redatte, rivelazione registrata, skill con codice rifiutata, nomi assenti dai log.
