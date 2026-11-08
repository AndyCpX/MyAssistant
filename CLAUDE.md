# MyAssistant – Smart speaker "JARVIS" (ESP32-S3 + agente Google ADK)

Assistente vocale in due parti: **firmware ESP-IDF** sulla scheda Waveshare ESP32-S3 AI Smart Speaker
(wake word, cattura audio, LED) e **servizio Python/Docker** in `agent/` (STT, agente LLM, TTS, riconoscimento parlante).
Lingua del progetto e dei commenti: italiano.

## Hardware (verificato con esptool il 2026-11-07)
- Chip: ESP32-S3 (QFN56) rev v0.2, dual core 240 MHz, Wi-Fi + BT5 LE, core LP
- Flash 16 MB (quad, 3.3 V, produttore 0x20 / dispositivo 0x4018), PSRAM 8 MB octal, quarzo 40 MHz
- USB: USB-Serial/JTAG nativo (VID `303A` / PID `1001`), porta **COM3** su questo PC
- MAC: `<MAC-scheda>`
- Pin (vedi `main/board.h`): I2C SDA 11 / SCL 10; I2S MCLK 12, BCLK 13, WS 14, DIN 15 (mic), DOUT 16 (speaker);
  anello LED WS2812B 7x su GPIO 38; codec ES8311 (speaker) e ES7210 (mic); expander TCA9555 per l'amplificatore NS4150B

### Collegamento / diagnostica
- Se Windows non vede la scheda (nessuna COM, nessun VID `303A`): **cambiare il cavo** (serve cavo dati). In questo progetto era quella la causa.
- Download mode: tieni premuto BOOT, premi RESET.
- `esptool` non è nel PATH; usare quello di ESP-IDF (v5.6.0, sintassi con trattini: `chip-id`, `flash-id`):
  `C:\Espressif\tools\python\v6.1\venv\Scripts\esptool.exe --port COM3 flash-id`
- Il `python` nel PATH è quello di ESP-IDF e non ha il modulo `esptool`.

## Firmware (`main/`)
- Toolchain: ESP-IDF v6.1 (`C:\Espressif`, richiesto >= 5.3). Aprire "ESP-IDF PowerShell" o caricare
  `C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1`. `.vscode/settings.json` punta a `C:\esp\v6.1\esp-idf`.
- Build e flash:
  ```powershell
  idf.py set-target esp32s3
  idf.py build
  idf.py -p COM3 flash monitor
  ```
- File: `main.c` (app_main, LED, macchina a stati), `audio.c` (I2C + TCA9555 + I2S duplex + ES8311/ES7210, 16 kHz),
  `wakeword.c` (esp-sr, AFE 2 mic, VAD), `streamer.c` (POST chunked all'agente), `net.c` (Wi-Fi), `player.c` (riproduzione risposta).
- Dipendenze (registry): `led_strip`, `esp_codec_dev`, `esp-sr`; `managed_components/` è generato (non modificare).
- Wake word: `wn9_jarvis_tts`, modello nella partizione `model`.
- Partizioni (`partitions.csv`): nvs, phy_init, factory app 4 MB, `model` 5 MB (spiffs), `storage` 5 MB (spiffs). Fine = 0xE10000.
- Configurazione locale: copia `sdkconfig.local.example` in `sdkconfig.local` (Wi-Fi SSID/password, `CONFIG_SS_SENTIMENT_URL`,
  `CONFIG_SS_AUTH_TOKEN`), poi `del sdkconfig` e `idf.py reconfigure`. `sdkconfig.local` non è versionato.
  Parametri nel menu "Smart Speaker": volume (default 70, valori alti distorcono), pausa di fine frase 500 ms,
  attesa parlato 5000 ms, durata massima 10000 ms.
- Colori anello LED: blu = avvio, verde tenue = in ascolto, ciano = wake word/streaming,
  verde/bianco/rosso = positive/neutral/negative, arancione = errore di rete/servizio, rosso fisso = errore init audio/wake word.
- Senza Wi-Fi configurato lo streaming è disattivato ma la wake word funziona comunque.

## Agente (`agent/`, Python 3.12, FastAPI + Google ADK)
- Avvio: `cd agent; copy .env.example .env; docker compose up --build` (porta 8080). `.env` non è versionato.
- Pipeline: audio PCM16 16 kHz mono -> STT (ElevenLabs Scribe, ripiego faster-whisper locale) -> agente ADK (LiteLLM,
  default Ollama Cloud) -> TTS Kokoro locale (`TTS_ENGINE`, ripiego ElevenLabs); in parallelo riconoscimento parlante (sherpa-onnx, soglia `SPEAKER_THRESHOLD`).
- Endpoint: `GET /healthz`, `POST /v1/utterance?rate=16000` (-> `{"label","transcript","reply"}`), `POST /v1/text`,
  `GET /v1/reply/{rid}` (audio risposta), `GET /v1/speakers`, `POST /v1/speakers/{name}/rename`, `DELETE /v1/speakers/{name}`.
- Auth opzionale con `AGENT_TOKEN` (Bearer). Sessione per dispositivo via header `X-Device-Id` (altrimenti IP), in memoria.
- Moduli: `main.py` (API), `agent.py` (agente ADK + tool `get_current_time`), `stt.py`, `tts.py`, `speaker.py`, `enrollment.py`.
- Variabili principali in `agent/.env.example`: `LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`, `LLM_THINK`, `STT_ENGINE`,
  `STT_MODEL`, `STT_LANGUAGE`, `ELEVENLABS_*`, `AGENT_LANGUAGE`, `AGENT_TIMEZONE` (default Europe/Rome).
- Test senza ESP32:
  ```powershell
  curl.exe -X POST localhost:8080/v1/text -H "Content-Type: application/json" -d "{\"text\":\"che ore sono?\"}"
  ```
- Volumi Docker: `whisper-models` (cache STT), `speaker-data` (voci registrate: dati biometrici, solo locali).

## Knowledge base (OKF)
La documentazione dettagliata è in `knowledge/`, un bundle [Open Knowledge Format](https://okf.md/skill/) v0.2 (parti da `knowledge/index.md`).
- Ogni file `.md` (tranne `index.md` e `log.md`) ha frontmatter YAML con `type` non vuoto; link con percorso assoluto dalla radice del bundle.
- Quando cambi hardware, firmware, API o configurazione, aggiorna il concetto relativo e aggiungi una riga in `knowledge/log.md` (date più recenti in alto).
- Niente segreti nel bundle.

## Note per Claude
- Non committare né stampare segreti: `agent/.env`, `sdkconfig.local`, API key, token.
- `build/`, `sdkconfig`, `managed_components/`, `.vscode/` sono ignorati da git (e il progetto non è attualmente un repo git).
- Il firmware usa solo il campo `label` della risposta; `transcript` e `reply` finiscono nel log seriale.
- TODO storici dal README: pin mapping completo dallo schema Waveshare.
