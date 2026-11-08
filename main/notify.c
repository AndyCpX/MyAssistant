#include "notify.h"
#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "mqtt_client.h"

// Notifiche per questa scheda: topic jarvis/notify/<id>, conferme su jarvis/ack/<id>.
// Il messaggio MQTT contiene solo {"id", "priority"}: il testo lo chiede la scheda all'agente.
// Il gestore degli eventi MQTT non fa HTTP: accoda soltanto l'id (il lavoro lo fa il loop principale).

static const char *TAG = "notify";

#define ID_LEN     40          // ids di 32 caratteri esadecimali + margine
#define QUEUE_LEN  4
#define BODY_MAX   768         // risposta di /speak: testo + audio (sotto 1 KB)

static esp_mqtt_client_handle_t s_mqtt;
static QueueHandle_t s_queue;
static volatile bool s_connected;

static bool valid_id(const char *id)
{
    size_t n = strlen(id);
    return n >= 8 && n < ID_LEN && strspn(id, "0123456789abcdef") == n;
}

// "http://host:port/qualcosa" -> "http://host:port" (stessa base del player)
static size_t agent_base_len(void)
{
    const char *base = CONFIG_SS_SENTIMENT_URL;
    const char *host = strstr(base, "://");
    host = host ? host + 3 : base;
    const char *slash = strchr(host, '/');
    return slash ? (size_t)(slash - base) : strlen(base);
}

static void on_mqtt_event(void *arg, esp_event_base_t base, int32_t event_id, void *event_data)
{
    esp_mqtt_event_handle_t ev = event_data;
    char topic[64];
    snprintf(topic, sizeof topic, "jarvis/notify/%s", CONFIG_SS_DEVICE_ID);

    switch (ev->event_id) {
    case MQTT_EVENT_CONNECTED:
        s_connected = true;
        esp_mqtt_client_subscribe(s_mqtt, topic, 1);
        ESP_LOGI(TAG, "MQTT connesso, in ascolto su %s", topic);
        break;
    case MQTT_EVENT_DISCONNECTED:
        s_connected = false;
        ESP_LOGW(TAG, "MQTT disconnesso (riconnessione automatica)");
        break;
    case MQTT_EVENT_DATA: {
        if (ev->topic_len != (int)strlen(topic) || strncmp(ev->topic, topic, ev->topic_len) != 0) break;
        cJSON *root = cJSON_ParseWithLength(ev->data, ev->data_len);
        const cJSON *id = root ? cJSON_GetObjectItemCaseSensitive(root, "id") : NULL;
        if (cJSON_IsString(id) && valid_id(id->valuestring)) {
            char buf[ID_LEN];
            snprintf(buf, sizeof buf, "%s", id->valuestring);
            if (xQueueSend(s_queue, buf, 0) != pdTRUE) {
                ESP_LOGW(TAG, "coda piena: notifica %s ripresa dal servizio piu' tardi", buf);
            } else {
                ESP_LOGI(TAG, "notifica ricevuta: %s", buf);
            }
        } else {
            ESP_LOGW(TAG, "messaggio non valido ignorato");
        }
        cJSON_Delete(root);
        break;
    }
    case MQTT_EVENT_ERROR:
        ESP_LOGW(TAG, "errore MQTT (tipo %d)", ev->error_handle ? ev->error_handle->error_type : -1);
        break;
    default:
        break;
    }
}

esp_err_t notify_start(void)
{
    if (strlen(CONFIG_SS_MQTT_URI) == 0) return ESP_ERR_INVALID_STATE;
    if (s_mqtt) return ESP_OK;
    s_queue = xQueueCreate(QUEUE_LEN, ID_LEN);
    if (!s_queue) return ESP_ERR_NO_MEM;

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = CONFIG_SS_MQTT_URI,
        .credentials.username = CONFIG_SS_DEVICE_ID,
        .credentials.client_id = CONFIG_SS_DEVICE_ID,
        .credentials.authentication.password = CONFIG_SS_MQTT_PASSWORD,
        .session.keepalive = 30,
    };
    s_mqtt = esp_mqtt_client_init(&cfg);
    if (!s_mqtt) return ESP_FAIL;
    esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, on_mqtt_event, NULL);
    return esp_mqtt_client_start(s_mqtt);
}

bool notify_next(char *id, size_t n)
{
    if (!s_queue || n < ID_LEN) return false;
    char buf[ID_LEN];
    if (xQueueReceive(s_queue, buf, 0) != pdTRUE) return false;
    snprintf(id, n, "%s", buf);
    return true;
}

esp_err_t notify_fetch(const char *id, char *audio_path, size_t n)
{
    if (!valid_id(id)) return ESP_ERR_INVALID_ARG;

    char url[192];
    size_t base = agent_base_len();
    if (snprintf(url, sizeof url, "%.*s/v1/notifications/%s/speak", (int)base, CONFIG_SS_SENTIMENT_URL, id) >= (int)sizeof url) {
        return ESP_ERR_INVALID_SIZE;
    }

    esp_http_client_config_t cfg = { .url = url, .method = HTTP_METHOD_POST, .timeout_ms = 10000, .buffer_size = 512 };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) return ESP_ERR_NO_MEM;
    esp_http_client_set_header(c, "X-Device-Id", CONFIG_SS_DEVICE_ID);
    if (strlen(CONFIG_SS_AUTH_TOKEN)) {
        char auth[160];
        snprintf(auth, sizeof auth, "Bearer %s", CONFIG_SS_AUTH_TOKEN);
        esp_http_client_set_header(c, "Authorization", auth);
    }

    esp_err_t ret = ESP_FAIL;
    static char body[BODY_MAX];   // statico: lo stack del task principale e' gia' occupato dal player
    int len = 0;
    if (esp_http_client_open(c, 0) != ESP_OK || esp_http_client_fetch_headers(c) < 0) {
        ESP_LOGE(TAG, "connessione all'agente fallita");
        goto done;
    }
    int status = esp_http_client_get_status_code(c);
    if (status == 404) { ret = ESP_ERR_NOT_FOUND; goto done; }
    if (status != 200) { ESP_LOGE(TAG, "agente: HTTP %d", status); goto done; }

    while (len < BODY_MAX - 1) {
        int r = esp_http_client_read(c, body + len, BODY_MAX - 1 - len);
        if (r <= 0) break;
        len += r;
    }
    body[len] = '\0';

    cJSON *root = cJSON_Parse(body);
    const cJSON *audio = root ? cJSON_GetObjectItemCaseSensitive(root, "audio") : NULL;
    if (cJSON_IsString(audio) && strncmp(audio->valuestring, "/v1/reply/", 10) == 0 &&
        strlen(audio->valuestring) < n) {
        snprintf(audio_path, n, "%s", audio->valuestring);
        ret = ESP_OK;
    } else {
        ESP_LOGW(TAG, "risposta senza audio");
    }
    cJSON_Delete(root);

done:
    esp_http_client_close(c);
    esp_http_client_cleanup(c);
    return ret;
}

void notify_ack(const char *id)
{
    if (!s_mqtt || !s_connected || !valid_id(id)) {
        ESP_LOGW(TAG, "conferma %s non inviata (MQTT non connesso): il servizio la ripropone", id);
        return;
    }
    char topic[64], payload[64];
    snprintf(topic, sizeof topic, "jarvis/ack/%s", CONFIG_SS_DEVICE_ID);
    snprintf(payload, sizeof payload, "{\"id\":\"%s\"}", id);
    esp_mqtt_client_publish(s_mqtt, topic, payload, 0, 1, 0);
    ESP_LOGI(TAG, "conferma inviata: %s", id);
}
