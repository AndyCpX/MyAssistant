# Update Log

## 2026-11-07
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
