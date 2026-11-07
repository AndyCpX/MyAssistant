---
type: Design
title: Memoria delle preferenze utente (Qdrant)
description: Progetto, non ancora implementato, per ricordare le preferenze del parlante e usarle nelle conversazioni vocali.
tags: [qdrant, memoria, preferenze, embedding]
status: draft
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
---

# Memoria delle preferenze utente

**Stato: progetto approvato nelle linee guida, nessun codice scritto.** Estende la [pipeline](/agent/pipeline.md)
dell'agente, che oggi tiene solo la sessione di conversazione in memoria. Il parlante arriva già da `speaker.py`
e `agent.ask(device_id, text, speaker)` lo riceve come argomento.

## Decisioni
| Tema | Scelta |
|---|---|
| Database | Qdrant open source, in Docker locale con volume dedicato |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX, locale, gratuito), 384 dimensioni, coseno |
| Scadenza | 90 giorni scorrevoli (`expires_at`), `pinned` esclusi |
| Parlante incerto | utente `guest`: nessuna lettura e nessuna scrittura di preferenze |
| Memorie dedotte | salvate solo dopo che si ripetono; quelle esplicite subito |

Prima di fissare il modello verificare che sia nell'elenco di `TextEmbedding.list_supported_models()` della versione installata.

## Collezione `user_memories`
Una sola collezione per tutti gli utenti, con payload index su `user_id` (approccio multi-tenant consigliato da Qdrant).

```json
{
  "id": "uuid",
  "vector": [ "... 384 float ..." ],
  "payload": {
    "user_id": "andrea",
    "kind": "preference",
    "key": "music.genre",
    "text": "Ad Andrea piace il jazz, soprattutto la sera.",
    "value": { "genre": "jazz", "when": "sera" },
    "pinned": false,
    "status": "active",
    "supersedes": null,
    "source": "explicit",
    "confidence": 0.9,
    "seen_count": 1,
    "evidence": "mettimi un po' di jazz come sempre",
    "device_id": "esp32-s3-9b80",
    "created_at": "2026-11-07T10:00:00Z",
    "updated_at": "2026-11-07T10:00:00Z",
    "last_used_at": null,
    "use_count": 0,
    "expires_at": "2027-02-05T10:00:00Z"
  }
}
```

- `kind`: `preference`, `fact`, `routine`, `relationship`, `style`.
- `key`: chiave normalizzata (es. `music.genre`) per riconoscere la stessa informazione e sostituirla invece di accumularla.
- `source`: `explicit` ("ricordati che…") oppure `inferred` (dedotta dall'LLM).
- `status`: `candidate`, `active`, `superseded`, `deleted`. Le sostituite non si cancellano subito, così "annulla" funziona.
- `pinned`: sempre iniettata nel prompt, senza ricerca (lingua, come chiamarlo, tono).
- Collezione/registro `users`: nome, lingua, forma di indirizzo, `speaker_name` collegato all'enrollment, consensi.

## Memorie dedotte: salvate dopo la ripetizione
Una preferenza dedotta non diventa subito attiva.
1. L'estrazione propone un candidato; si cerca il più simile dello stesso `user_id` e `key`.
2. Se non esiste, si crea con `status: candidate` e `seen_count: 1`. I candidati **non vengono mai usati nelle risposte**.
3. Se si ripresenta (similarità alta sulla stessa `key`) in una conversazione diversa, `seen_count` sale.
4. Al raggiungimento della soglia (proposta: `MEMORY_PROMOTE_AFTER=2`) lo stato passa a `active` e parte il TTL di 90 giorni.
5. Se contraddice una memoria attiva, la vecchia diventa `superseded` solo quando la nuova è promossa.
6. Proposta da confermare: i candidati non ripetuti scadono prima (es. 30 giorni).

Le memorie `explicit` saltano la fase di candidato e sono attive subito con `confidence` alta.

## Scadenza (TTL)
Qdrant non ha una scadenza nativa.
- `expires_at` = `updated_at` o `last_used_at` + 90 giorni; si rinnova quando la memoria viene usata o riconfermata.
- Ogni ricerca filtra `expires_at > now`, quindi la scadenza vale anche se la pulizia non è girata.
- Un job periodico (una volta al giorno, nel processo dell'agente) elimina i punti scaduti.

## Parlante incerto
- Si usa una soglia più alta di `SPEAKER_THRESHOLD` (0.65): proposta `PERSONALIZATION_THRESHOLD` ~0.75, da calibrare sul log.
- Tra le due soglie l'agente può usare il nome ma non le memorie.
- Se il secondo candidato ha un punteggio vicino (margine piccolo) il caso è trattato come incerto.
- La stessa regola vale per le scritture: nessuna preferenza salvata con identità dubbia.

## Flusso live
**Lettura** (nel percorso della richiesta):
1. Identificazione del parlante; se incerto, `guest` e si salta tutto.
2. Embedding del testo trascritto, in parallelo con la preparazione della chiamata all'LLM.
3. Ricerca con filtro `user_id = X AND status = active AND expires_at > now`, top 4-5, soglia minima di score, più le `pinned`.
4. I testi finiscono in un blocco del prompt ("Cosa sai dell'utente: …"); `last_used_at`, `use_count` ed `expires_at` si aggiornano in background.

Obiettivo di latenza: embedding più ricerca sotto circa 50-100 ms.

**Scrittura** (dopo la risposta, in background): estrazione dei candidati, deduplica, promozione come sopra.

## Endpoint di gestione previsti
Sul modello di `/v1/speakers` ([API](/agent/api.md)):
- `GET /v1/memories?user=`
- `DELETE /v1/memories/{id}`
- `DELETE /v1/memories?user=` (oblio totale)

## Infrastruttura prevista
Servizio `qdrant` nel `docker-compose.yml` con volume proprio; cache del modello di embedding nel volume `whisper-models`
([configurazione](/agent/configuration.md)). Come per le voci registrate, i dati restano solo in locale.

## Da definire in implementazione
- Soglia di similarità per "stessa informazione" (deduplica e ripetizione), da calibrare su esempi reali.
- Soglia esatta di `PERSONALIZATION_THRESHOLD` e del margine sul secondo candidato.
- Quale modello fa l'estrazione dei candidati (lo stesso LLM dell'agente o uno più piccolo).
