#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

/** Avvia il client MQTT delle notifiche. Richiede Wi-Fi. ESP_ERR_INVALID_STATE se SS_MQTT_URI e' vuoto. */
esp_err_t notify_start(void);

/** Prende la prossima notifica in attesa (id esadecimale). false se non ce ne sono. Non bloccante. */
bool notify_next(char *id, size_t n);

/**
 * Chiede all'agente il testo di una notifica (POST /v1/notifications/{id}/speak) e restituisce il percorso
 * dell'audio da riprodurre con player_play_path(). ESP_ERR_NOT_FOUND = notifica non destinata a questa
 * scheda o gia' annullata: va chiusa con notify_ack().
 */
esp_err_t notify_fetch(const char *id, char *audio_path, size_t n);

/** Conferma la notifica riprodotta. Se il broker non e' raggiungibile la conferma si perde e il servizio la ripropone. */
void notify_ack(const char *id);
