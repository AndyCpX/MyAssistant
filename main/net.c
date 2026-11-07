#include "net.h"
#include <string.h>
#include "esp_log.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

static const char *TAG = "net";

#define GOT_IP_BIT  BIT0
#define MAX_RETRIES 10

static EventGroupHandle_t s_ev;
static int s_retries;

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        // Riconnessione indefinita anche dopo il boot (router riavviato, ecc.)
        if (s_retries < MAX_RETRIES) {
            s_retries++;
        }
        ESP_LOGW(TAG, "Wi-Fi disconnesso, riprovo (%d)", s_retries);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "IP ottenuto: " IPSTR, IP2STR(&e->ip_info.ip));
        s_retries = 0;
        xEventGroupSetBits(s_ev, GOT_IP_BIT);
    }
}

esp_err_t net_init(void)
{
    if (strlen(CONFIG_SS_WIFI_SSID) == 0) {
        ESP_LOGW(TAG, "SS_WIFI_SSID non configurato: Wi-Fi disattivato");
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(err, TAG, "nvs");

    s_ev = xEventGroupCreate();
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), TAG, "wifi init");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL), TAG, "ev");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL), TAG, "ev");

    wifi_config_t wc = { 0 };
    strlcpy((char *)wc.sta.ssid, CONFIG_SS_WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, CONFIG_SS_WIFI_PASSWORD, sizeof(wc.sta.password));
    wc.sta.threshold.authmode = strlen(CONFIG_SS_WIFI_PASSWORD) ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wc), TAG, "cfg");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "start");
    esp_wifi_set_ps(WIFI_PS_NONE);   // niente modem sleep: latenza minima (lo speaker e' alimentato da rete)

    ESP_LOGI(TAG, "Connessione a '%s'...", CONFIG_SS_WIFI_SSID);
    EventBits_t bits = xEventGroupWaitBits(s_ev, GOT_IP_BIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(20000));
    ESP_RETURN_ON_FALSE(bits & GOT_IP_BIT, ESP_ERR_TIMEOUT, TAG, "nessun IP entro 20 s");
    return ESP_OK;
}
