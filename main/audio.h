#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "esp_codec_dev.h"

#define AUDIO_SAMPLE_RATE 16000

/** Inizializza I2C, TCA9555, I2S, ES8311 (speaker) ed ES7210 (mic). */
esp_err_t audio_init(void);
esp_err_t audio_pa_enable(bool on);
esp_codec_dev_handle_t audio_speaker(void);
esp_codec_dev_handle_t audio_mic(void);
