#pragma once
#include "esp_err.h"

/** Connette il Wi-Fi in modalità station e attende l'IP. ESP_ERR_INVALID_STATE se SSID non configurato. */
esp_err_t net_init(void);
