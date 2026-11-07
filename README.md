# Smart Speaker – Waveshare ESP32-S3 AI Smart Speaker

Progetto ESP-IDF (Espressif) per riprogrammare lo speaker.

## Hardware verificato
- ESP32-S3 (QFN56) rev v0.2, dual core 240 MHz
- Flash 16 MB, PSRAM 8 MB (octal), USB-Serial/JTAG

## Prerequisiti
- ESP-IDF >= 5.3 (testato con v6.1)
- Su Windows: aprire "ESP-IDF PowerShell" oppure caricare
  `C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1`

## Build / flash
```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COM3 flash monitor
```
Per entrare in download mode: tieni premuto BOOT, premi RESET.

## Struttura
- `main/main.c` – entry point (`app_main`)
- `sdkconfig.defaults` – flash 16MB, PSRAM octal
- `partitions.csv` – factory app 4MB + partizioni dati `model` 5MB e `storage` 5MB

## Audio
- `main/board.h` pin mapping, `main/audio.c` init I2C + TCA9555 (PA) + I2S duplex + ES8311 (speaker) + ES7210 (mic), 16 kHz
- Al boot: tono 440 Hz, poi 1s di registrazione con livello RMS; anello verde = ok, rosso = errore

## Wake word e sentiment
- Wake word: esp-sr `wn9_jarvis_tts` (AFE a 2 microfoni, VAD WebRTC)
- Dopo la wake word l'audio pulito (16 kHz mono PCM16) viene inviato con POST chunked a `agent/` fino a 500 ms di pausa
  (timeout: 3 s senza parlato, 10 s di durata massima; vedi menu Smart Speaker in menuconfig)
- Anello LED: verde tenue = in ascolto, ciano = streaming, verde/bianco/rosso = positive/neutral/negative, arancione = errore
- Configurazione Wi-Fi/URL: copia `sdkconfig.local.example` in `sdkconfig.local`, poi `del sdkconfig` e `idf.py reconfigure`

### Servizio (Google ADK, Docker)
Vedi `agent/README.md`: trascrizione (faster-whisper) + agente ADK; `POST /v1/utterance` (PCM16LE mono, `?rate=16000`) -> `{"label","transcript","reply"}`.

## TODO
- Pin mapping della scheda (I2C, I2S, expander IO, amplificatore) dallo schema Waveshare
- Wake word (esp-sr)
