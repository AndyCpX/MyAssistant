---
# Modello di skill dichiarativa (type: http). La cartella inizia con "_": viene ignorata dal caricatore.
# Copia la cartella con un altro nome (senza "_") e adatta i campi.
name: esempio
description: Descrizione breve mostrata all'LLM (una riga).
type: http
requires_env: [ESEMPIO_URL, ESEMPIO_TOKEN]     # se mancano la skill resta disattivata
triggers: [parola1, parola2]                   # vuoto = sempre offerta all'LLM
base_url_env: ESEMPIO_URL                      # host fisso da configurazione: l'LLM non sceglie mai l'URL
auth: { header: Authorization, value_env: ESEMPIO_TOKEN, prefix: "Bearer " }
tools:
  - name: leggi_stato
    description: Legge lo stato di un elemento.
    method: GET
    path: /api/items/{item_id}
    params:
      item_id: { type: string, required: true, in: path, description: "Identificativo dell'elemento" }
    extract: "state"                           # percorso a punti nella risposta JSON, es. a.b[0].c
  - name: imposta
    description: Imposta un valore.
    method: POST
    path: /api/items/{item_id}/set
    send: json
    params:
      item_id: { type: string, required: true, in: path }
      value: { type: integer, required: true, description: "Valore da 0 a 100" }
---

# Istruzioni per l'LLM (corpo di SKILL.md)
Scrivi qui, in markdown, come e quando usare questa skill. Il testo viene aggiunto al prompt solo quando la skill è attiva.
