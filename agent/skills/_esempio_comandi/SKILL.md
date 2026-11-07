---
# Modello di skill con comandi scelti dall'LLM. Inizia con "_": ignorata dal caricatore. Copia con un altro nome.
name: esempio_comandi
description: Interroga il servizio X della rete locale (stato dei dispositivi).
requires_env: [X_TOKEN, X_HOST]
commands:
  allow: [curl, jq]                # eseguibili ammessi (niente shell: pipe e redirezioni non funzionano)
  allowed_hosts: ["${X_HOST}"]     # obbligatorio con curl: ogni URL deve puntare a uno di questi host (porta opzionale)
  env: [X_TOKEN, X_HOST]           # variabili espandibili nei comandi ($NOME); il resto dell'ambiente viene rimosso
---

# Servizio X
Usa lo strumento `esegui_esempio_comandi` con una sola riga. Per leggere lo stato di un dispositivo:

    curl -s -H "Authorization: Bearer $X_TOKEN" http://$X_HOST/api/devices/ID

Scrivi `$X_TOKEN` e `$X_HOST` letteralmente: il sistema li sostituisce, e tu non vedi mai il valore del token.
Non c'è una shell: niente pipe, redirezioni o `$(...)`. Rispondi in una frase con lo stato letto.
