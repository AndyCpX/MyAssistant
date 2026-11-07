idf_component_register(SRCS "main.c" "audio.c" "wakeword.c" "net.c" "streamer.c" "player.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_driver_i2c esp_driver_i2s esp_driver_gpio
                                esp_wifi esp_netif esp_event nvs_flash esp_http_client esp_timer)
