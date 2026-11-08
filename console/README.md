# console — diagnostica di JARVIS

Console per uso personale: vedere i dispositivi, le persone, le memorie e le notifiche, e caricare una skill da zip.
È un servizio Python (FastAPI) con un'interfaccia in HTML e JavaScript senza build.

Non legge Qdrant né i file dei dati direttamente: passa dalle API dell'agente (`/v1/speakers`, `/v1/memories`,
`/v1/skills`, `/v1/devices`) e del servizio notify. Così la logica di memoria e voci resta in un solo posto.

## Funzioni

| Sezione | Cosa mostra | Dati personali |
|---|---|---|
| Dispositivi | schede che hanno interagito con l'agente dall'ultimo riavvio, ultimo parlante | ultimo parlante |
| Persone | nomi registrati, ruolo, campioni vocali, conteggio memorie per stato | nessun testo, nessuna voce |
| Memorie | per persona: tipo, chiave, stato, uso, scadenza | **testo nascosto** finché non lo richiedi |
| Notifiche | destinatario, sorgente, consegna, stato | **testo dei promemoria personali nascosto** |
| Skill | elenco con tipo, stato e problemi; caricamento zip; ricarica | — |
| Audit | rivelazioni e caricamenti, con data | non registra mai il testo |

Ogni rivelazione (`?reveal=1`) è registrata nell'audit con la persona e il numero di elementi, senza il contenuto.

## Caricamento di una skill (zip)

Lo zip deve contenere `SKILL.md` nella radice, oppure una sola cartella con `SKILL.md` dentro.
Controlli prima di scrivere su disco:

- dimensione massima 5 MB, massimo 200 file, massimo 20 MB scompressi, rapporto di compressione ≤ 100 (zip bomb);
- niente percorsi assoluti, `..`, backslash o link simbolici;
- niente file di codice (`.py`, `.sh`, `.js`, `.exe`, ...);
- solo tipi `instructions` e `http`; niente blocco `commands`;
- nome della cartella: lettere minuscole, cifre, `-` e `_`, da 2 a 40 caratteri;
- non sovrascrive una skill esistente (per aggiornarla rimuovi prima la cartella sul disco).

Dopo l'installazione la console chiede all'agente di ricaricare le skill. Con `CONSOLE_ALLOW_CODE_SKILLS=1`
i controlli sul codice vengono disattivati: da usare solo sapendo che quel codice gira nel container dell'agente.

## Configurazione

Nel compose dell'agente (`agent/docker-compose.yml`), con le variabili in `agent/.env`:

- `CONSOLE_TOKEN` (obbligatorio): token di accesso. Senza, il servizio non parte.
- `AGENT_TOKEN`, `NOTIFY_TOKEN`: gli stessi dei rispettivi servizi.
- `CONSOLE_ALLOW_CODE_SKILLS`: `0` (predefinito).

La porta è pubblicata solo su `127.0.0.1:8090`. Non esporla su Internet né sulla LAN.

## Avvio

```powershell
cd agent
docker compose up -d --build console
```

Poi apri http://127.0.0.1:8090, inserisci il `CONSOLE_TOKEN` e scegli la sezione.

## Test

```powershell
cd console
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## Note

- Il token resta nella sessione del browser (`sessionStorage`) e si cancella chiudendo la scheda.
- L'access log di uvicorn è disattivato: i percorsi contengono nomi di persone.
- Le schede "attive" sono quelle che hanno interagito con l'agente dall'ultimo riavvio, non un heartbeat.
  Un heartbeat vero richiederebbe un messaggio periodico dal firmware su MQTT.
- Per gli elenchi "Persone" e "Memorie" la console interroga l'agente per ogni persona: con molte persone va paginato.
