#pragma once
#include "esp_err.h"

typedef void (*wakeword_cb_t)(void);

/** Avvia i task di feed (mic -> AFE) e fetch (rilevamento wake word). Richiede audio_init(). */
esp_err_t wakeword_start(wakeword_cb_t on_detect);

/** Richiede una nuova sessione di ascolto senza wake word (l'assistente ha fatto una domanda). */
void wakeword_request_follow_up(void);
