# JARVIS agent (Google ADK, Docker)

Riceve dall'ESP32 l'audio dopo la wake word JARVIS (PCM16 16 kHz mono, POST chunked fino a 500 ms di pausa),
lo trascrive (faster-whisper, locale) e lo passa a un agente Google ADK. Risponde `{"label","transcript","reply"}`.

## Avvio
```powershell
cd agent
copy .env.example .env      # imposta LLM_API_KEY (Ollama Cloud) e, volendo, AGENT_TOKEN
docker compose up --build
```
Test senza ESP32:
```powershell
curl.exe -X POST localhost:8080/v1/text -H "Content-Type: application/json" -d "{\"text\":\"che ore sono?\"}"
curl.exe -X POST "localhost:8080/v1/utterance?rate=16000" -H "Transfer-Encoding: chunked" --data-binary "@frase.pcm"
```

## Firmware
In `sdkconfig.local`: `CONFIG_SS_SENTIMENT_URL="http://<ip-host>:8080/v1/utterance"` (+ `CONFIG_SS_AUTH_TOKEN` = `AGENT_TOKEN`).
Il firmware non cambia: usa solo il campo `label` (anello bianco); `transcript`/`reply` finiscono nel log seriale.

## Configurazione LLM
`LLM_MODEL` / `LLM_API_BASE` / `LLM_API_KEY` accettano qualsiasi modello LiteLLM (vedi `.env.example`).
Sessione di conversazione per dispositivo (header `X-Device-Id`, altrimenti IP), in memoria.
