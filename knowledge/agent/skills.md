---
type: Design
title: Skill dinamiche, tool use e comandi dell'agente
description: Skill in formato SKILL.md (agent/app/skills.py) con istruzioni, tool http e python, e comandi eseguibili scelti dall'LLM.
tags: [skills, tool-use, comandi, sicurezza, adk]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
verified: { by: human:andyc, at: 2026-11-07T00:00:00Z }
---

# Skill dinamiche

Estendono l'agente con cartelle in `agent/skills/<nome>/`, senza ricostruire l'immagine. Il formato è `SKILL.md`: frontmatter YAML
più istruzioni in markdown. `skill.yaml` resta accettato (senza istruzioni). Implementazione in `agent/app/skills.py`
(caricatore, tool) e `agent/app/commands.py` (comandi). Home Assistant è solo un esempio di skill possibile.

## Decisioni
| Tema | Scelta |
|---|---|
| Formato | `SKILL.md` (frontmatter + corpo); le cartelle che iniziano con `_` sono ignorate |
| Cosa può dare una skill | istruzioni, tool `http`, tool `python`, comandi |
| Caricamento | all'avvio e con `POST /v1/skills/reload` (nessun osservatore di file) |
| Attivazione | trigger (opzionali) oppure similarità richiesta-descrizione con embedding locali |
| Controllo per utente | non previsto: tutti i parlanti possono usare le skill |
| Comandi | eseguiti nel container dell'agente, argomenti liberi per l'LLM (scelta del proprietario, vedi rischi) |

## Formato di SKILL.md
```markdown
---
name: meteo
description: Tempo attuale e previsioni per una città.       # indice e attivazione per similarità
triggers: [meteo, piove, temperatura]                        # opzionale: attivano la skill con certezza
requires_env: [CHIAVE]                                       # se mancano la skill resta disattivata
tools: [meteo]                                               # funzioni di tools.py (python) oppure tool http in YAML
commands:                                                    # opzionale: comandi scelti dall'LLM
  allow: [curl, jq]
  allowed_hosts: ["api.example.com", "${HOST}"]              # obbligatorio con curl
  env: [TOKEN]                                               # variabili espandibili ($TOKEN) nei comandi
---

# Istruzioni
Testo in markdown iniettato nel prompt solo quando la skill è attiva (massimo `SKILL_BODY_MAX`, 3000 caratteri).
```
Il tipo è dedotto: `python` se esiste `tools.py`, `http` se `tools` contiene dizionari, altrimenti `instructions`.

### Tool `http` (equivalente dichiarativo di curl)
Richieste con host fisso (`base_url_env`), `auth` da variabile d'ambiente, parametri tipizzati (`in: path` per i segmenti),
`extract` come percorso a punti (`a.b[0].c`), timeout 8 s, redirect non seguiti, risposta troncata a 1500 caratteri.
Modello in `skills/_esempio_http/SKILL.md`.

### Tool `python`
`tools.py` con funzioni dotate di type hint e docstring (ADK ne ricava lo schema). Esempio: `skills/meteo/`.

### Comandi
Uno strumento `esegui_<skill>` accetta una riga di comando. Modello in `skills/_esempio_comandi/SKILL.md`.
Il sistema espande `$NOME` e `${NOME}` **solo** per le variabili dichiarate in `env`: l'LLM scrive il segnaposto e non vede mai il valore.

## Attivazione
Una skill è attiva per la richiesta se compare un trigger, oppure se la similarità coseno tra la richiesta e la `description`
è almeno `SKILL_MIN_SCORE` (0.35). Resta attiva per 120 s nei follow-up della stessa sessione. Senza trigger e senza embedder è sempre attiva.
Gli embedding sono quelli locali condivisi con la [memoria utente](/agent/user-memory.md) (`agent/app/embed.py`).

Calibrazione (MiniLM, campione piccolo): richieste pertinenti da 0.39 a 0.75, non pertinenti fino a 0.31. Con 0.30 "che ore sono"
attivava il meteo, per questo il default è 0.35. Limite: richieste senza parole della descrizione ("come si fa la carbonara" contro
"ricette di cucina") restano sotto soglia; conviene descrizioni con esempi concreti e trigger per le parole chiave.

## Sicurezza dei comandi
Scelta del proprietario: i comandi girano **nel container dell'agente** (che contiene chiavi API e voci registrate) con argomenti liberi.
Per ridurre il rischio:
- niente shell: la riga è spezzata con `shlex` ed eseguita come `argv`; pipe, redirezioni e `$(...)` non funzionano;
- solo gli eseguibili elencati in `allow`, senza percorsi (`/bin/ls` rifiutato);
- processo figlio come `nobody` (uid 65534), senza gruppi, con `setuid` in `preexec_fn` (compatibile con uvloop);
- ambiente ripulito: solo `PATH`, `HOME`, `LANG` e le variabili dichiarate; le chiavi dell'agente non ci sono;
- `/data` (voci registrate) portata a permessi 700 all'avvio; `/proc/1/environ` non leggibile dal figlio;
- cartella temporanea per ogni comando, timeout 10 s, limiti di CPU, file (1 MB), processi e memoria, output massimo 64 KB;
- segreti delle variabili dichiarate sostituiti con `***` nell'output restituito all'LLM;
- nei log solo skill, esito e durata.

**curl** ha controlli aggiuntivi: `allowed_hosts` obbligatorio; ogni URL deve avere host (e porta, se indicata) ammessi; schemi solo
http/https; vietati `-o/-O/-T/-x/-F/-L/-b/-c/-D/-v/-K`, `--proxy`, `--resolve`, `--unix-socket`, `--config`, `--trace*` e simili; dati
`@file` rifiutati; URL con `{}` o `[]` rifiutati; credenziali nell'URL (`host@evil`) non aggirano il controllo. `wget` non è supportato.

### Rischi residui (accettati)
- Per gli eseguibili diversi da curl vale solo l'allowlist: `cat`, `ls` e simili leggono ciò che l'utente `nobody` può leggere
  (codice in `/srv/app`, modelli, `/srv/skills`). I segreti non sono lì, ma il codice sì.
- Un `curl` verso un host ammesso può fare tutto ciò che quell'host consente, con il token della skill.
- Prompt injection: testo trascritto o risposte di terzi potrebbero spingere l'LLM a chiamare comandi ammessi. Il prompt dice di trattare
  l'output come dato, ma non è una garanzia.
- Qdrant (`qdrant:6333`, senza autenticazione) è raggiungibile dal container: una skill con `allowed_hosts` che lo includa
  esporrebbe memorie e trascritti. Non aggiungerlo mai agli host ammessi. L'alternativa più sicura resta un container separato
  senza segreti né volumi.

## Come aggiungere una skill
1. Crea `agent/skills/<nome>/SKILL.md` (parti da un modello `_esempio_*`).
2. Metti le variabili richieste in `agent/.env`.
3. `curl.exe -X POST localhost:8080/v1/skills/reload` e controlla `GET /v1/skills`: `problem` spiega perché una skill è disattivata.

## Verificato
- Test isolato: host non ammessi, flag vietati, `@file`, schemi diversi da http, espansioni, `;`, eseguibili non ammessi, percorsi
  assoluti, utente `nobody`, `/data` e `/proc/1/environ` negati, ambiente ripulito, token sostituito e censurato, timeout.
- End to end con l'LLM reale: tool python (`meteo`, 325 ms), tool http con server di prova, comando `curl` scelto dall'LLM
  (226 ms) e isolamento confermato nel processo reale sotto uvloop.
- Un difetto trovato in produzione e corretto: uvloop rifiuta `user/group` in `create_subprocess_exec`, quindi i privilegi si
  abbandonano in `preexec_fn`.

## Non ancora supportato
- Tipo `mcp`; `confirm: true` (accettato, ignorato con avviso).
- Script allegati alla skill (`scripts/`): oggi si eseguono solo gli eseguibili di sistema in `allow`.
- Tool `http` provato solo con un server di prova, non con un servizio reale.

## Skill di terzi: script, filtro jq e skill.local.yaml (2026-11-07)
Provate con `anotb/homeassistant-skill` (formato standard, pensata per agenti con shell). Tre estensioni:
- **`skill.local.yaml`** nella cartella della skill: chiavi che sovrascrivono il frontmatter (`description`, `triggers`, `requires_env`,
  `commands`) e `instructions`, che sostituisce il corpo di SKILL.md. Serve per adattare una skill di terzi (descrizione e istruzioni
  in italiano per la voce) senza modificare i suoi file, che un aggiornamento sovrascriverebbe. Attenzione: in YAML una descrizione
  con `: ` va messa tra virgolette, altrimenti la skill risulta disattivata con `ScannerError`.
- **`commands.scripts`**: elenco di script `.py` dentro la cartella della skill. Si lanciano per nome (`scripts/ha_read.py get ...`),
  eseguiti con `python -I` come `nobody`. È diverso da ammettere `python3`, che con argomenti liberi equivarrebbe a codice arbitrario.
  Gli script vanno letti prima di abilitarli: sono codice di terzi che riceve le variabili dichiarate.
- **`filtro_jq`**: parametro opzionale dello strumento (se `jq` è in `allow`). Senza shell non ci sono pipe, quindi l'output del comando
  (fino a 8 MB) passa per `jq -c <filtro>` in un secondo processo, senza le variabili segrete nell'ambiente. Il filtro non può iniziare con `-`.
  Un filtro jq può leggere file leggibili da `nobody`, stesso rischio residuo di `cat`.
Il nome dello strumento sostituisce i caratteri non alfanumerici con `_` (`esegui_homeassistant_skill`).

### Home Assistant (sola lettura)
`skills/homeassistant-skill` + `skill.local.yaml`: `HA_URL` e `HA_TOKEN` in `agent/.env`. Lo script `ha_read.py` usa solo la libreria standard,
parla solo con `HA_URL`, consente GET su percorsi in allowlist, non segue redirect e censura il token (letto prima di abilitarlo).
Verificato con "elenca tutte le luci": strumento in 205 ms, risposta con i nomi leggibili in 2,9 s.
Il controllo dei dispositivi (accendere/spegnere) **non è abilitato**: richiederebbe `curl` con `allowed_hosts: ["${HA_URL host}"]` e chiamate
a `/api/services/...`, cioè un'azione sul mondo fisico scelta dall'LLM.

### curl abilitato per Home Assistant (2026-11-07)
La skill ora ammette `curl` oltre allo script di sola lettura, quindi l'LLM può **agire sui dispositivi** (turn_on, turn_off, toggle).
Controlli aggiunti in `commands.py` / `skills.py`:
- `allowed_hosts` accetta anche URL (`"${HA_URL}"`): viene ridotto a `host:porta`. Una variabile non definita fa scartare la voce e,
  se non resta nessun host, la skill resta disattivata (`expandvars` altrimenti la lascia letterale).
- `allowed_paths`: regole `"METODO regex"` sul percorso dell'URL. Con le regole presenti, ogni richiesta deve corrispondere esattamente a una.
  Il metodo effettivo è `-X`, altrimenti POST se ci sono dati, altrimenti GET. **curl ammette solo GET e POST** (DELETE e PUT rifiutati).
- Regole di Home Assistant: `GET /api/states` e `/api/states/<entity>`; `POST /api/services/<dominio>/<servizio>` per i domini
  light, switch, scene, climate, fan, media_player, input_boolean, input_number, input_select, vacuum.
  **Esclusi:** lock, alarm_control_panel, cover (tapparelle e garage), script, automation, homeassistant, notify, shell_command,
  hassio, `/api/config`, `/api/events`, `POST /api/states/...` (stati falsi). Per includere un dominio, aggiungilo nella regex di `skill.local.yaml`.
- Il blocco è duro (codice), non solo istruzioni al modello: una richiesta fuori regola non esce dal container.
- Log: il motivo di rifiuto o il codice di uscita compaiono sempre (`rifiutato/fallito`); la riga scritta dall'LLM solo con
  `SKILL_LOG_COMMANDS=1` (contiene i segnaposto `$HA_TOKEN`, non i valori).

Verificato: server finto con casi ammessi (letture, `turn_on` con token sostituito) e 10 casi vietati (lock, allarme, restart, DELETE, PUT,
stato falso, config, `..`, dati su GET, host esterno): nessuna richiesta è arrivata al server. Con Home Assistant reale solo **letture**
("quali luci sono accese?", "elenca tutte le luci", "quali interruttori ci sono?"). Nessuna azione è stata eseguita sulla casa.
Un errore iniziale (jq codice 5) era dovuto a un esempio sbagliato nelle istruzioni (`and` dentro `select` con la pipe): corretto con filtri esatti.

### Tapparelle (cover) abilitate (2026-11-07)
Regola aggiunta: `POST /api/services/cover/(open_cover|close_cover|stop_cover|set_cover_position|toggle)`. Non ammessi gli altri servizi
`cover` (es. `open_cover_tilt`). Letto l'elenco reale: 10 entità `cover`, nove con `device_class: shutter` e una, `cover.sonoff_10025f56ec`
("MINI-RBS", stato open), senza tipo. La regola filtra il **servizio**, non l'entità: in Home Assistant anche garage e cancelli sono
`cover`. Mitigazione solo nelle istruzioni (non agire su garage, cancelli, porte), quindi non è un blocco duro. Per un blocco duro servirebbe
restringere le entità (non supportato oggi: le regole guardano solo metodo e percorso). Nessuna azione eseguita sulle tapparelle reali.
