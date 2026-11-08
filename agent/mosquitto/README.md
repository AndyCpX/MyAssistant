# Broker MQTT per le schede (Mosquitto)

Il broker consegna alle schede le notifiche dovute dal servizio `notify/`. Sul broker
transitano solo gli id delle notifiche e la priorità: il testo viene chiesto all'agente
(`POST /v1/notifications/{id}/speak`), così i promemoria personali non passano in chiaro.

Il broker è raggiungibile dalla LAN sulla porta 1883 e richiede utente e password.
Permessi con il plugin `dynamic-security`: ogni scheda ha un ruolo che le consente
solo `jarvis/notify/<id>` (lettura) e `jarvis/ack/<id>` (scrittura); tutto il resto è negato.

## Primo avvio

Le password reali non vanno nel repo: scegline di lunghe e tienile in un gestore di password.

```powershell
cd agent
# 1) inizializza dynamic-security nel volume mqtt-data (solo la prima volta)
docker compose run --rm --no-deps --entrypoint mosquitto_ctrl mqtt dynsec init /mosquitto/data/dynamic-security.json admin <PASSWORD_ADMIN>
# 2) avvia il broker
docker compose up -d mqtt
# 3) crea utente notify e una scheda per ogni dispositivo (es. kitchen, bedroom)
bash mosquitto/provision.sh <PASSWORD_ADMIN> <PASSWORD_NOTIFY> kitchen:<PASSWORD_KITCHEN> bedroom:<PASSWORD_BEDROOM>
```

In `agent/.env` imposta `MQTT_NOTIFY_PASSWORD=<PASSWORD_NOTIFY>` e `NOTIFY_DEVICES=kitchen,bedroom`.
La password della scheda va nella configurazione del firmware (`sdkconfig.local`), mai nel repo.

Lo script richiede bash (Git Bash su Windows) e Docker Compose in esecuzione. Può essere rieseguito:
gli errori "already exists" sono attesi e non cambiano la configurazione.

## Verifica

- Scheda senza permesso: `mosquitto_sub` o una sottoscrizione a `jarvis/notify/<altro>` deve fallire con `Unspecified error`.
- Connessione anonima: deve essere rifiutata (`Not authorized`).
- Pubblicazione di una notifica dal servizio `notify` (vedi `notify/README.md`): la scheda la riceve su `jarvis/notify/<id>`.

## Note

- Le ACL del file `acl` non sono usate: con Mosquitto il default era «consenti» e le regole non negavano nulla.
- In dynamic-security il `%u` funziona per la pubblicazione ma non per la sottoscrizione letterale: i topic dei ruoli sono scritti per esteso.
- TLS non è attivo: il traffico è in chiaro sulla LAN. Accettabile perché il broker non trasporta testo; da riconsiderare se il broker esce dalla LAN.
