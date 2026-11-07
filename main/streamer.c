#include "streamer.h"
#include "player.h"
#include "wakeword.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_check.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"

static const char *TAG = "streamer";

#define FRAME_BYTES   6144                 // 3072 campioni = 192 ms: pochi chunk grandi, Nagle/ACK ritardati non rallentano l'upload
#define BUFFER_BYTES  (384 * 1024)         // ~12 s di audio, in PSRAM: copre la connessione + 10 s di parlato

static StreamBufferHandle_t s_sb;
static StaticStreamBuffer_t *s_sb_struct;
static uint8_t *s_sb_storage;
static TaskHandle_t s_task;
static sentiment_cb_t s_cb;
static volatile bool s_busy, s_finish, s_abort;

static bool send_chunk(esp_http_client_handle_t c, const uint8_t *data, int len, bool last)
{
    if (esp_http_client_chunk_write_begin(c, len) < 0) return false;
    if (esp_http_client_write(c, (const char *)data, len) != len) return false;
    return esp_http_client_chunk_write_end(c, last) == 0;
}

// Copia in out il valore stringa di "key":"..." (senza gestire escape). out vuoto se assente o troppo lungo.
static void json_str(const char *body, const char *key, char *out, size_t out_size)
{
    out[0] = 0;
    char pat[24];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(body, pat);
    if (!p || !(p = strchr(p + strlen(pat), ':'))) return;
    while (*++p == ' ') {}
    if (*p != '"') return;
    const char *start = p + 1, *end = strchr(start, '"');
    if (!end || (size_t)(end - start) >= out_size) return;
    memcpy(out, start, end - start);
    out[end - start] = 0;
}

static void parse_response(const char *body, sentiment_result_t *res)
{
    json_str(body, "label", res->label, sizeof(res->label));
    json_str(body, "audio", res->audio, sizeof(res->audio));
    res->follow_up = strstr(body, "\"follow_up\":true") != NULL;
    const char *p = strstr(body, "\"score\"");
    if (p && (p = strchr(p, ':'))) {
        res->score = strtof(p + 1, NULL);
    }
}

static void run_session(void)
{
    sentiment_result_t res = { .status = STREAM_ERROR };
    uint8_t *frame = heap_caps_malloc(FRAME_BYTES * 2, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    uint8_t *pending = frame + FRAME_BYTES;
    int pending_len = 0;
    esp_http_client_handle_t c = NULL;
    if (!frame) goto done;

    esp_http_client_config_t cfg = {
        .url = CONFIG_SS_SENTIMENT_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 25000,   // STT + LLM possono richiedere diversi secondi
        .buffer_size = 1024,
    };
    c = esp_http_client_init(&cfg);
    if (!c) goto done;
    esp_http_client_set_header(c, "Content-Type", "audio/L16; rate=16000; channels=1");
    if (strlen(CONFIG_SS_AUTH_TOKEN)) {
        char auth[160];
        snprintf(auth, sizeof(auth), "Bearer %s", CONFIG_SS_AUTH_TOKEN);
        esp_http_client_set_header(c, "Authorization", auth);
    }
    // write_len = -1 => Transfer-Encoding: chunked; il body viene inviato mentre si parla
    if (esp_http_client_open(c, -1) != ESP_OK) {
        ESP_LOGE(TAG, "connessione a %s fallita", CONFIG_SS_SENTIMENT_URL);
        goto done;
    }

    // Si invia con un chunk di ritardo: l'ultimo chunk deve portare il terminatore.
    while (!s_abort) {
        // Accumula fino a FRAME_BYTES (o fino a fine enunciato / pausa del flusso)
        int n = 0;
        while (n < FRAME_BYTES && !s_abort) {
            int r = xStreamBufferReceive(s_sb, frame + n, FRAME_BYTES - n, pdMS_TO_TICKS(40));
            if (r > 0) { n += r; continue; }
            break;                                   // nulla di nuovo: invia quanto accumulato
        }
        if (n > 0) {
            if (pending_len > 0 && !send_chunk(c, pending, pending_len, false)) {
                ESP_LOGE(TAG, "scrittura chunk fallita");
                goto done;
            }
            memcpy(pending, frame, n);
            pending_len = n;
        } else if (s_finish && xStreamBufferIsEmpty(s_sb)) {
            break;
        }
    }
    if (s_abort) {
        res.status = STREAM_ABORTED;
        goto done;
    }
    if (pending_len == 0 || !send_chunk(c, pending, pending_len, true)) {
        ESP_LOGE(TAG, "chiusura stream fallita");
        goto done;
    }

    if (esp_http_client_fetch_headers(c) < 0) {
        ESP_LOGE(TAG, "nessuna risposta");
        goto done;
    }
    int status = esp_http_client_get_status_code(c);
    char body[512];
    int len = esp_http_client_read_response(c, body, sizeof(body) - 1);
    body[len > 0 ? len : 0] = 0;
    if (status != 200) {
        ESP_LOGE(TAG, "HTTP %d: %s", status, body);
        goto done;
    }
    ESP_LOGI(TAG, "risposta: %s", body);
    parse_response(body, &res);
    res.status = res.label[0] ? STREAM_OK : STREAM_ERROR;
    ESP_LOGI(TAG, "audio risposta: '%s'", res.audio);

done:
    if (c) {
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
    }
    free(frame);
    if (s_cb) s_cb(&res);
    if (res.status == STREAM_OK && res.audio[0]) {
        player_play_path(res.audio);   // s_busy resta true: nessuna nuova sessione durante la risposta
    }
    if (res.status == STREAM_OK && res.follow_up) {
        ESP_LOGI(TAG, "domanda dell'assistente: riapro l'ascolto");
        wakeword_request_follow_up();
    }
}

static void streamer_task(void *arg)
{
    while (1) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        run_session();
        s_busy = false;
    }
}

esp_err_t streamer_init(sentiment_cb_t cb)
{
    s_cb = cb;
    s_sb_storage = heap_caps_malloc(BUFFER_BYTES + 1, MALLOC_CAP_SPIRAM);
    s_sb_struct = heap_caps_malloc(sizeof(StaticStreamBuffer_t), MALLOC_CAP_INTERNAL);
    ESP_RETURN_ON_FALSE(s_sb_storage && s_sb_struct, ESP_ERR_NO_MEM, TAG, "buffer");
    s_sb = xStreamBufferCreateStatic(BUFFER_BYTES, 1, s_sb_storage, s_sb_struct);
    ESP_RETURN_ON_FALSE(s_sb, ESP_ERR_NO_MEM, TAG, "stream buffer");
    ESP_RETURN_ON_FALSE(xTaskCreatePinnedToCore(streamer_task, "streamer", 8192, NULL, 4, &s_task, 0) == pdPASS,
                        ESP_ERR_NO_MEM, TAG, "task");
    ESP_LOGI(TAG, "pronto -> %s", CONFIG_SS_SENTIMENT_URL);
    return ESP_OK;
}

bool streamer_begin(void)
{
    if (!s_task || s_busy) return false;
    xStreamBufferReset(s_sb);
    s_finish = false;
    s_abort = false;
    s_busy = true;
    xTaskNotifyGive(s_task);
    return true;
}

void streamer_push(const int16_t *pcm, size_t samples)
{
    if (!s_busy || s_finish) return;
    xStreamBufferSend(s_sb, pcm, samples * sizeof(int16_t), 0);
}

void streamer_finish(void) { s_finish = true; }

void streamer_abort(void)
{
    s_abort = true;
    s_finish = true;
}
