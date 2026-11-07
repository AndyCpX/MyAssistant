---
type: Design
title: Telemetria di sessioni, modelli e dispositivi
description: Progetto, non ancora implementato, per tracciare sessioni, turni, componenti, costi e metriche dell'ESP32 con Phoenix, SQLite e Grafana.
tags: [telemetria, phoenix, opentelemetry, grafana, sqlite, costi]
status: draft
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Telemetria

**Stato: progetto, nessun codice scritto.** Riguarda la [pipeline](/agent/pipeline.md) dell'agente, il
[firmware](/firmware/modules.md) e, a tendere, la [memoria utente](/agent/user-memory.md).

## Obiettivo
Capire per ogni sessione le interazioni con l'utente, i modelli usati, i componenti coinvolti, i dati del caso (inclusi i
trascritti), i costi stimati e lo stato del dispositivo ESP32.

## Decisioni
| Tema | Scelta |
|---|---|
| Tracce | OpenTelemetry verso **Phoenix** (Arize), locale e gratuito |
| Dati dei turni | tabella piatta in **SQLite** (per ora; Postgres resta possibile in seguito) |
| Dashboard | Phoenix per sessioni e flusso, **Grafana** per dispositivi e aggregati; nessuna dashboard custom per ora |
| Trascritti | salvati per intero, solo in locale |
| Costi | stimati per ogni componente |
| Firmware | invia metriche fin dalla prima versione |

## Modello: sessione, turno, span
- **Sessione**: conversazione continua con un dispositivo. Si chiude dopo un intervallo di inattività (proposta: 5 minuti,
  configurabile). Oggi la sessione ADK è legata a `X-Device-Id` e vive in memoria, quindi serve un `session_id` esplicito.
- **Turno**: un giro completo, dalla wake word alla fine della riproduzione.
- **Span**: un componente dentro il turno.

Span previsti per turno: `wake`, `stream`, `speaker_id`, `stt`, `memory_retrieve`, `llm` (con eventuali `tool`), `tts`, `playback`,
`memory_write`.

## Identificativi
Il firmware aggiunge a ogni richiesta, oltre a `X-Device-Id`, un `X-Turn-Id` generato da lui. L'agente assegna o riprende il
`session_id` in base all'inattività e lo usa come attributo `session.id` delle tracce, così Phoenix le raggruppa per
sessione (vista Sessions: da verificare nella versione installata). Va usato anche `trace_id` nella tabella `turns` per
collegare la riga alla traccia.

## Cosa si registra per turno
| Componente | Dati |
|---|---|
| Firmware | versione, motivo dell'ultimo reset, RSSI, heap libero, PSRAM libera, punteggio della wake word |
| Stream | durata, byte inviati, motivo di chiusura (pausa, nessun parlato, massimo) |
| Parlante | nome scelto, punteggio, margine sul secondo candidato, decisione (noto, incerto, ospite) |
| STT | motore (Scribe o locale), modello, latenza, testo, ripiego usato, secondi di audio |
| Memoria | memorie recuperate (id e score), quante iniettate, candidati creati o promossi |
| LLM | modello, token in e out, latenza, tempo al primo token, tool chiamati |
| TTS | motore, caratteri, latenza, durata dell'audio |
| Esito | `label`, errori, latenza totale da fine parlato a primo audio |
| Trascritti | testo dell'utente e risposta, interi |

La metrica guida è la **latenza end to end**, scomposta per componente.

## Costi stimati
Calcolati per turno e salvati sia come attributo dello span sia nella colonna `cost_*` di `turns`.
- **LLM**: token in e out × prezzo del modello. Phoenix conosce i prezzi dei modelli noti; per Ollama Cloud e per i modelli
  locali serve una tabella prezzi propria.
- **STT**: Scribe a secondi di audio; faster-whisper locale vale 0.
- **TTS**: ElevenLabs a caratteri, secondo il piano.
- Modelli locali ed embedding: 0 in denaro (la corrente non è stimata).

La tabella prezzi sta in un file di configurazione, unico punto da aggiornare. I costi sono stime.

## SQLite: tabelle
Database nel volume dati dell'agente (da aggiungere al compose, come `speaker-data`).

`turns` (una riga per turno):
```sql
turn_id TEXT PRIMARY KEY, session_id TEXT, trace_id TEXT, device_id TEXT,
started_at TEXT, user_id TEXT, speaker_score REAL, speaker_margin REAL, speaker_decision TEXT,
wake_score REAL, stream_ms INTEGER, stream_bytes INTEGER, stream_end TEXT,
stt_engine TEXT, stt_model TEXT, stt_ms INTEGER, stt_fallback INTEGER, audio_s REAL,
transcript TEXT, reply TEXT, label TEXT,
mem_retrieved INTEGER, mem_injected INTEGER, mem_candidates INTEGER, mem_promoted INTEGER,
llm_model TEXT, tokens_in INTEGER, tokens_out INTEGER, llm_ms INTEGER, llm_ttft_ms INTEGER, tool_calls TEXT,
tts_engine TEXT, tts_chars INTEGER, tts_ms INTEGER, tts_audio_s REAL,
e2e_ms INTEGER, error TEXT,
cost_llm REAL, cost_stt REAL, cost_tts REAL, cost_total REAL
```

`sessions`: `session_id`, `device_id`, `user_id`, `started_at`, `ended_at`, `turn_count`, `cost_total`.

`device_metrics` (serie temporale dal firmware):
```sql
ts TEXT, device_id TEXT, fw_version TEXT, reset_reason TEXT, uptime_s INTEGER,
rssi INTEGER, heap_free INTEGER, heap_min INTEGER, psram_free INTEGER, wifi_reconnects INTEGER
```

## Metriche dell'ESP32
Inviate dal firmware a intervalli (proposta: ogni 60 s) con `POST /v1/telemetry`, oltre agli header per turno:
- versione del firmware e motivo dell'ultimo reset
- uptime e riconnessioni Wi-Fi
- RSSI
- heap libero, minimo storico e PSRAM libera
- per ogni turno: punteggio della wake word, durata e byte dello stream

Il minimo storico dell'heap è utile per scoprire perdite di memoria. Il firmware oggi stampa la PSRAM libera solo al boot.

## Dashboard
- **Phoenix**: vista a cascata del flusso di un turno, prompt, risposta, token e tool; sessioni raggruppate per `session.id`.
- **Grafana**: serie temporali del dispositivo, percentili di latenza, errori e costi per giorno, per modello e per utente,
  con un link dalla riga del turno alla traccia in Phoenix.
- Grafana legge SQLite tramite un plugin della community (non firmato, da verificare). Se dà problemi la strada è Postgres.
- Una dashboard custom si valuta solo dopo alcune settimane d'uso, se il salto tra i due strumenti dà fastidio.

## Privacy
I trascritti completi e le preferenze sono dati personali; restano solo in locale.
- L'audio grezzo non si salva di default (eventuale interruttore di debug a tempo).
- Retention dei trascritti configurabile, più un comando per cancellare tutto di un utente, come per la memoria.
- Chiavi API e token non devono comparire nelle tracce.

## Fasi
1. `session_id`, `turn_id`, timer per componente e tabella `turns` con costi.
2. OpenTelemetry verso Phoenix e tabella prezzi.
3. Telemetria del firmware (`device_metrics`) e dashboard Grafana.

## Da definire
- Intervallo di inattività che chiude la sessione.
- Periodo di retention dei trascritti.
- Prezzi effettivi dei piani (ElevenLabs, Ollama Cloud) per la tabella costi.
- Verifica di strumentazione OTel di ADK, vista Sessions di Phoenix e plugin SQLite per Grafana nelle versioni installate.
