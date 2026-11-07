#include "wakeword.h"
#include "audio.h"
#include "streamer.h"
#include "player.h"
#include "esp_vad.h"
#include "esp_log.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "model_path.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_models.h"
#include "esp_afe_sr_iface.h"

static const char *TAG = "wakeword";

static const esp_afe_sr_iface_t *s_afe;
static esp_afe_sr_data_t *s_afe_data;
static wakeword_cb_t s_cb;
static int s_feed_samples;   // campioni per canale per chiamata a feed
static int s_feed_channels;
static volatile int64_t s_follow_deadline_us;   // 0 = nessuna richiesta di follow-up

static void feed_task(void *arg)
{
    size_t bytes = s_feed_samples * s_feed_channels * sizeof(int16_t);
    int16_t *buf = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!buf) {
        ESP_LOGE(TAG, "feed: malloc fallita");
        vTaskDelete(NULL);
    }
    int frames = 0;
    while (1) {
        if (esp_codec_dev_read(audio_mic(), buf, bytes) == ESP_CODEC_DEV_OK) {
            if (++frames % 31 == 0) {   // ~2 s a 16 kHz con frame da 1024 campioni
                int n = s_feed_samples * s_feed_channels, peak = 0;
                for (int i = 0; i < n; i++) { int a = buf[i] < 0 ? -buf[i] : buf[i]; if (a > peak) peak = a; }
                ESP_LOGI(TAG, "livello mic: picco=%d", peak);
            }
            s_afe->feed(s_afe_data, buf);
        } else {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}

typedef enum {
    ST_IDLE,          // in attesa della wake word
    ST_WAIT_SPEECH,   // wake word rilevata, il VAD non ha ancora visto parlato
    ST_SPEAKING,      // parlato in corso: si invia l'audio finche' c'e' una pausa di END_SILENCE_MS
} detect_state_t;

static void detect_task(void *arg)
{
    detect_state_t state = ST_IDLE;
    int elapsed_ms = 0;    // dalla wake word
    int silence_ms = 0;    // pausa consecutiva dopo il parlato

    while (1) {
        afe_fetch_result_t *res = s_afe->fetch(s_afe_data);
        if (!res || res->ret_value == ESP_FAIL) {
            continue;
        }
        int samples = res->data_size / sizeof(int16_t);
        int frame_ms = samples * 1000 / AUDIO_SAMPLE_RATE;

        if (state == ST_IDLE && s_follow_deadline_us) {
            if (esp_timer_get_time() > s_follow_deadline_us) {
                s_follow_deadline_us = 0;                       // nessuno streamer libero in tempo: rinuncio
            } else if (!player_active() && streamer_begin()) {
                s_follow_deadline_us = 0;
                ESP_LOGI(TAG, "ascolto senza wake word (risposta alla domanda)");
                if (s_cb) {
                    s_cb();
                }
                state = ST_WAIT_SPEECH;
                elapsed_ms = 0;
                silence_ms = 0;
                continue;
            }
        }

        if (state == ST_IDLE) {
            if (res->wakeup_state != WAKENET_DETECTED || player_active()) {
                continue;   // niente wake word mentre lo speaker parla
            }
            ESP_LOGI(TAG, "Wake word rilevata! (indice %d, canale %d)", res->wake_word_index,
                     res->trigger_channel_id);
            if (s_cb) {
                s_cb();
            }
            if (streamer_begin()) {
                state = ST_WAIT_SPEECH;
                elapsed_ms = 0;
                silence_ms = 0;
            } else {
                ESP_LOGW(TAG, "streaming non disponibile (rete assente o sessione in corso)");
            }
            continue;
        }

        // Sessione di streaming attiva: l'audio e' quello pulito dall'AFE (mono, 16 kHz)
        streamer_push(res->data, samples);
        elapsed_ms += frame_ms;

        if (state == ST_WAIT_SPEECH) {
            if (res->vad_state == VAD_SPEECH) {
                ESP_LOGI(TAG, "parlato rilevato dopo %d ms", elapsed_ms);
                state = ST_SPEAKING;
            } else if (elapsed_ms >= CONFIG_SS_WAIT_SPEECH_MS) {
                ESP_LOGW(TAG, "nessun parlato entro %d ms: annullo", CONFIG_SS_WAIT_SPEECH_MS);
                streamer_abort();
                state = ST_IDLE;
            }
        } else {   // ST_SPEAKING
            silence_ms = (res->vad_state == VAD_SPEECH) ? 0 : silence_ms + frame_ms;
            if (silence_ms >= CONFIG_SS_END_SILENCE_MS) {
                ESP_LOGI(TAG, "pausa di %d ms: fine enunciato (%d ms inviati)", silence_ms, elapsed_ms);
                streamer_finish();
                state = ST_IDLE;
            } else if (elapsed_ms >= CONFIG_SS_MAX_UTTERANCE_MS) {
                ESP_LOGW(TAG, "durata massima raggiunta (%d ms)", elapsed_ms);
                streamer_finish();
                state = ST_IDLE;
            }
        }
    }
}

void wakeword_request_follow_up(void)
{
    s_follow_deadline_us = esp_timer_get_time() + 4 * 1000 * 1000;   // il task di rete si libera subito dopo
}

esp_err_t wakeword_start(wakeword_cb_t on_detect)
{
    s_cb = on_detect;

    srmodel_list_t *models = esp_srmodel_init("model");
    ESP_RETURN_ON_FALSE(models && models->num > 0, ESP_FAIL, TAG, "nessun modello nella partizione 'model'");
    for (int i = 0; i < models->num; i++) {
        ESP_LOGI(TAG, "modello: %s", models->model_name[i]);
    }
    char *wn = esp_srmodel_filter(models, ESP_WN_PREFIX, NULL);
    ESP_RETURN_ON_FALSE(wn, ESP_FAIL, TAG, "nessun modello wakenet");
    ESP_LOGI(TAG, "wake word model: %s", wn);

    // 2 microfoni (ES7210 MIC1+MIC2), nessun canale di riferimento
    afe_config_t *cfg = afe_config_init("MM", models, AFE_TYPE_SR, AFE_MODE_LOW_COST);
    ESP_RETURN_ON_FALSE(cfg, ESP_FAIL, TAG, "afe_config_init");
    cfg->wakenet_model_name = wn;
    cfg->aec_init = false;           // niente riferimento playback
    cfg->vad_init = true;
    cfg->vad_min_noise_ms = 96;      // il VAD segnala la pausa quasi subito; i 500 ms li conta detect_task
    cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    cfg = afe_config_check(cfg);
    afe_config_print(cfg);

    s_afe = esp_afe_handle_from_config(cfg);
    ESP_RETURN_ON_FALSE(s_afe, ESP_FAIL, TAG, "afe handle");
    s_afe_data = s_afe->create_from_config(cfg);
    ESP_RETURN_ON_FALSE(s_afe_data, ESP_FAIL, TAG, "afe create");

    s_feed_samples = s_afe->get_feed_chunksize(s_afe_data);
    s_feed_channels = s_afe->get_feed_channel_num(s_afe_data);
    ESP_LOGI(TAG, "AFE: %d campioni x %d canali per feed, %d Hz", s_feed_samples, s_feed_channels,
             s_afe->get_samp_rate(s_afe_data));
    ESP_RETURN_ON_FALSE(s_feed_channels == 2, ESP_FAIL, TAG, "canali feed inattesi: %d", s_feed_channels);

    xTaskCreatePinnedToCore(feed_task, "afe_feed", 4096, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(detect_task, "afe_detect", 6144, NULL, 5, NULL, 1);
    ESP_LOGI(TAG, "In ascolto della wake word");
    return ESP_OK;
}
