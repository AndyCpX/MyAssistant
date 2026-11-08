#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"
#include "audio.h"
#include "wakeword.h"
#include "net.h"
#include "streamer.h"
#include "notify.h"
#include "player.h"
#include <string.h>
#include "board.h"

static const char *TAG = "smart_speaker";

#define RGB_LED_COUNT 7   // anello 7x WS2812B

static led_strip_handle_t rgb_init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = BOARD_RGB_GPIO,
        .max_leds = RGB_LED_COUNT,
    };
    led_strip_rmt_config_t rmt_cfg = {
        .resolution_hz = 10 * 1000 * 1000,
    };
    led_strip_handle_t strip = NULL;
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &strip));
    led_strip_clear(strip);
    return strip;
}

static void rgb_fill(led_strip_handle_t strip, uint8_t r, uint8_t g, uint8_t b)
{
    for (int i = 0; i < RGB_LED_COUNT; i++) {
        led_strip_set_pixel(strip, i, r, g, b);
    }
    led_strip_refresh(strip);
}

static volatile bool s_wake;
static volatile bool s_has_result;
static sentiment_result_t s_result;

static void on_wake(void)
{
    s_wake = true;
}

static void on_sentiment(const sentiment_result_t *res)
{
    s_result = *res;
    s_has_result = true;
}

static void show_result(led_strip_handle_t rgb, const sentiment_result_t *r)
{
    ESP_LOGI(TAG, "sentiment: status=%d label=%s score=%.2f", r->status, r->label, r->score);
    if (r->status == STREAM_ABORTED) {
        return;                                    // niente da mostrare
    }
    if (r->status == STREAM_ERROR) {
        rgb_fill(rgb, 60, 30, 0);                  // arancione = errore di rete/servizio
    } else if (strcmp(r->label, "positive") == 0) {
        rgb_fill(rgb, 0, 80, 0);                   // verde acceso
    } else if (strcmp(r->label, "negative") == 0) {
        rgb_fill(rgb, 80, 0, 0);                   // rosso
    } else {
        rgb_fill(rgb, 40, 40, 40);                 // bianco = neutro
    }
    vTaskDelay(pdMS_TO_TICKS(2500));
}

// Notifica dal servizio (via MQTT): chiede il testo all'agente, la riproduce e la conferma.
// Senza conferma (errore di rete o riproduzione fallita) il servizio la ripropone: nessuna notifica si perde.
static void handle_notification(led_strip_handle_t rgb, const char *id)
{
    ESP_LOGI(TAG, "notifica %s: chiedo il testo all'agente", id);
    rgb_fill(rgb, 40, 20, 0);                       // ambra = notifica in corso
    char audio[64] = {0};
    esp_err_t err = notify_fetch(id, audio, sizeof audio);
    if (err == ESP_ERR_NOT_FOUND) {
        ESP_LOGW(TAG, "notifica %s non destinata a questa scheda o annullata: chiusa", id);
        notify_ack(id);
    } else if (err == ESP_OK && player_play_path(audio) == ESP_OK) {
        notify_ack(id);
    } else {
        ESP_LOGW(TAG, "notifica %s non consegnata: sara' riproposta", id);
    }
    rgb_fill(rgb, 0, 10, 0);
}

void app_main(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);
    ESP_LOGI(TAG, "ESP32-S3 Smart Speaker avviato (%d core, rev %d)", info.cores, info.revision);
    ESP_LOGI(TAG, "PSRAM libera: %u byte", (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    led_strip_handle_t rgb = rgb_init();
    rgb_fill(rgb, 0, 0, 40);   // blu (luminosita' ridotta)
    ESP_LOGI(TAG, "LED RGB: blu");

    // Rete + streaming sono opzionali: senza Wi-Fi la wake word funziona comunque
    bool streaming = false;
    if (net_init() == ESP_OK && streamer_init(on_sentiment) == ESP_OK) {
        streaming = true;
    } else {
        ESP_LOGW(TAG, "streaming sentiment disattivato");
    }

    if (streaming) {
        esp_err_t nerr = notify_start();
        if (nerr == ESP_OK) ESP_LOGI(TAG, "notifiche MQTT attive");
        else if (nerr == ESP_ERR_INVALID_STATE) ESP_LOGI(TAG, "notifiche MQTT disattivate (SS_MQTT_URI vuoto)");
        else ESP_LOGW(TAG, "notifiche MQTT non avviate: %s", esp_err_to_name(nerr));
    }

    if (audio_init() != ESP_OK || wakeword_start(on_wake) != ESP_OK) {
        ESP_LOGE(TAG, "Init audio/wake word fallita");
        rgb_fill(rgb, 40, 0, 0);   // rosso = errore
        while (1) { vTaskDelay(pdMS_TO_TICKS(1000)); }
    }
    rgb_fill(rgb, 0, 10, 0);       // verde tenue = in ascolto

    while (1) {
        if (s_wake) {
            s_wake = false;
            s_has_result = false;
            rgb_fill(rgb, 0, 40, 40);              // ciano = wake word rilevata / stream in corso
            // Attende il risultato (max 15 s); senza streaming torna subito in ascolto
            int waited = 0;
            while (streaming && !s_has_result && waited < 15000) {
                vTaskDelay(pdMS_TO_TICKS(50));
                waited += 50;
            }
            if (!streaming) {
                vTaskDelay(pdMS_TO_TICKS(1500));
            } else if (s_has_result) {
                show_result(rgb, &s_result);
            } else {
                ESP_LOGW(TAG, "nessun risultato entro 15 s");
            }
            s_has_result = false;
            s_wake = false;
            rgb_fill(rgb, 0, 10, 0);
        }
        char pending[40];
        if (!s_wake && notify_next(pending, sizeof pending)) {
            handle_notification(rgb, pending);
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}
