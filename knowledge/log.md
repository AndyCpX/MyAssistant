# Update Log

## 2026-11-08
- **Update**: [notifications](/agent/notifications.md): firmware con client MQTT (`main/notify.c`) per le notifiche; verificato su hardware con una notifica di prova dal servizio notify: ricevuta, riprodotta, confermata. Password di prova ancora in `sdkconfig.local` locale da cambiare.
- **Creation**: [console](/agent/console.md): console di diagnostica Python (FastAPI, HTML senza build) su 127.0.0.1:8090: dispositivi, persone, memorie redatte con rivelazione in audit, notifiche, caricamento skill da zip con controlli di sicurezza; endpoint agente `GET /v1/devices`. Verificata con l'agente reale.
- **Update**: [notifications](/agent/notifications.md): consegna alle schede via Mosquitto (dynamic-security, default deny, un ruolo per scheda), ack dopo riproduzione, token per sorgente e limite di frequenza; verificato nello stack compose con schede simulate. Firmware non ancora aggiornato.
- **Creation**: [notifications](/agent/notifications.md): servizio eventi `notify/` separato dall'agente (coda SQLite, lease, ack), tool `set_reminder` e polling su agente; test 17/17, firmware non ancora aggiornato.
- **Update**: [pipeline](/agent/pipeline.md) e [configuration](/agent/configuration.md): TTS locale con Kokoro (kokoro-onnx, voce `if_sara`) come default, ElevenLabs come ripiego (`TTS_ENGINE`); provato in italiano nel container (RTF ~0,15), ripiego verificato.

## 2026-11-07
- **Update**: [skills](/agent/skills.md): luci.py per accendere/spegnere le luci in una chiamata; causa di "spegni tutte" trovata nel limite 429 di Netatmo.
- **Update**: [skills](/agent/skills.md): gli switch senza device_class sono trattati come luci in Home Assistant; letture verificate.
- **Update**: [skills](/agent/skills.md): tapparelle (cover) abilitate per Home Assistant con servizi limitati; elenco reale letto, nessuna azione eseguita.
- **Update**: [skills](/agent/skills.md): curl abilitato per Home Assistant con allowed_paths, solo GET e POST, domini esclusi e blocco duro; solo letture provate sulla casa reale.
- **Update**: [skills](/agent/skills.md): skill.local.yaml, commands.scripts e filtro_jq; skill Home Assistant in sola lettura provata con "elenca tutte le luci".
- **Update**: [skills](/agent/skills.md) passa al formato SKILL.md, aggiunge i comandi scelti dall'LLM (utente nobody, curl con host ammessi) e l'attivazione per similarità.
- **Update**: [skills](/agent/skills.md) implementata (http e python, reload a caldo, skill meteo) e provata end to end.
- **Creation**: Aggiunto [skills](/agent/skills.md), progetto in bozza delle skill dinamiche con tool use (http, python, mcp; reload esplicito).
- **Update**: [user-memory](/agent/user-memory.md) implementata in agent/app/memory.py: soglie calibrate sul modello, limiti noti e parti da verificare.
- **Creation**: Aggiunto [telemetry](/agent/telemetry.md), progetto in bozza della telemetria (Phoenix, SQLite, Grafana, costi stimati, metriche ESP32).
- **Creation**: Aggiunto [user-memory](/agent/user-memory.md), progetto in bozza della memoria delle preferenze con Qdrant (TTL 90 giorni, salvataggio dopo ripetizione, nessuna personalizzazione con parlante incerto).
- **Creation**: Creato il bundle OKF con le sezioni hardware, firmware, agent, troubleshooting e decisions.
- **Verification**: Hardware verificato con esptool v5.6.0 su COM3 (chip-id, flash-id).
- **Initialization**: Bundle creato.
