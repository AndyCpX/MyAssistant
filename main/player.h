#pragma once
#include <stdbool.h>
#include "esp_err.h"

/** Scarica da `base URL del server` + `path` un PCM16 mono 16 kHz e lo riproduce mentre arriva. Bloccante. */
esp_err_t player_play_path(const char *path);

/** true durante la riproduzione e per un breve intervallo dopo: la wake word va ignorata (eco dello speaker). */
bool player_active(void);
