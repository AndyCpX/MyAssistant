#include "player.h"
#include <stdio.h>
#include <string.h>
#include "audio.h"
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

static const char *TAG = "player";

#define COOLDOWN_US    (700 * 1000)         // coda di eco dopo la fine dell'audio

static volatile bool s_playing;
static volatile int64_t s_until_us;

bool player_active(void)
{
    return s_playing || esp_timer_get_time() < s_until_us;
}

// "http://host:port/qualcosa" + "/v1/reply/x" -> "http://host:port/v1/reply/x"
static bool build_url(char *out, size_t n, const char *path)
{
    const char *base = CONFIG_SS_SENTIMENT_URL;
    const char *host = strstr(base, "://");
    host = host ? host + 3 : base;
    const char *slash = strchr(host, '/');
    size_t base_len = slash ? (size_t)(slash - base) : strlen(base);
    return snprintf(out, n, "%.*s%s", (int)base_len, base, path) < (int)n;
}

#define MAX_CLIP_BYTES (1024 * 1024)       // ~32 s di PCM16 16 kHz mono, in PSRAM
#define PREROLL_FRAMES (16 * 120)          // 120 ms di silenzio: l'amplificatore si stabilizza prima della voce
#define TAIL_FRAMES    (16 * 300)          // 300 ms di silenzio: il DMA finisce di suonare prima di spegnere il PA
#define CHUNK_FRAMES   1024

// Scrive n frame di silenzio stereo
static void write_silence(int16_t *stereo, int frames)
{
    memset(stereo, 0, CHUNK_FRAMES * 4);
    while (frames > 0) {
        int n = frames > CHUNK_FRAMES ? CHUNK_FRAMES : frames;
        esp_codec_dev_write(audio_speaker(), stereo, n * 4);
        frames -= n;
    }
}

esp_err_t player_play_path(const char *path)
{
    char url[192];
    if (!build_url(url, sizeof(url), path)) return ESP_ERR_INVALID_SIZE;

    // 1) Scarica tutta la risposta in PSRAM: la riproduzione non dipende piu' dalla rete.
    uint8_t *clip = heap_caps_malloc(MAX_CLIP_BYTES, MALLOC_CAP_SPIRAM);
    int16_t *stereo = heap_caps_malloc(CHUNK_FRAMES * 4, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    esp_http_client_config_t cfg = { .url = url, .method = HTTP_METHOD_GET, .timeout_ms = 15000, .buffer_size = 1024 };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    esp_err_t ret = ESP_FAIL;
    size_t got = 0;
    if (!clip || !stereo || !c) goto done;

    if (strlen(CONFIG_SS_AUTH_TOKEN)) {
        char auth[160];
        snprintf(auth, sizeof(auth), "Bearer %s", CONFIG_SS_AUTH_TOKEN);
        esp_http_client_set_header(c, "Authorization", auth);
    }
    s_playing = true;
    int64_t t0 = esp_timer_get_time();
    if (esp_http_client_open(c, 0) != ESP_OK || esp_http_client_fetch_headers(c) < 0) {
        ESP_LOGE(TAG, "connessione a %s fallita", url);
        goto done;
    }
    int status = esp_http_client_get_status_code(c);
    if (status != 200) {
        ESP_LOGE(TAG, "HTTP %d", status);
        goto done;
    }
    while (got < MAX_CLIP_BYTES) {
        size_t want = MAX_CLIP_BYTES - got;
        int n = esp_http_client_read(c, (char *)clip + got, want > 4096 ? 4096 : want);
        if (n < 0) {
            if (got == 0) { ESP_LOGE(TAG, "lettura fallita"); goto done; }
            ESP_LOGW(TAG, "flusso interrotto dopo %u byte: riproduco quanto ricevuto", (unsigned)got);
            break;
        }
        if (n == 0) {
            if (esp_http_client_is_complete_data_received(c)) break;
            continue;
        }
        got += n;
    }
    size_t samples = got / 2;
    ESP_LOGI(TAG, "scaricati %u campioni (%u ms di audio) in %d ms", (unsigned)samples, (unsigned)(samples / 16),
             (int)((esp_timer_get_time() - t0) / 1000));
    if (samples == 0) goto done;

    // 2) Riproduzione: pre-roll di silenzio, voce (mono -> stereo), coda di silenzio, poi PA spento.
    const int16_t *pcm = (const int16_t *)clip;
    audio_pa_enable(true);
    write_silence(stereo, PREROLL_FRAMES);
    for (size_t pos = 0; pos < samples; pos += CHUNK_FRAMES) {
        int n = samples - pos > CHUNK_FRAMES ? CHUNK_FRAMES : (int)(samples - pos);
        for (int i = 0; i < n; i++) {
            stereo[2 * i] = pcm[pos + i];
            stereo[2 * i + 1] = pcm[pos + i];
        }
        esp_codec_dev_write(audio_speaker(), stereo, n * 4);
    }
    write_silence(stereo, TAIL_FRAMES);
    audio_pa_enable(false);
    ret = ESP_OK;

done:
    if (c) { esp_http_client_close(c); esp_http_client_cleanup(c); }
    free(clip);
    free(stereo);
    s_until_us = esp_timer_get_time() + COOLDOWN_US;
    s_playing = false;
    return ret;
}
