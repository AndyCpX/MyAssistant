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
