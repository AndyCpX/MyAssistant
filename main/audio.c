#include "audio.h"
#include "board.h"
#include "esp_log.h"
#include "esp_check.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev_defaults.h"
#include "es8311_codec.h"
#include "es7210_adc.h"

static const char *TAG = "audio";

static i2c_master_bus_handle_t s_i2c;
static i2c_master_dev_handle_t s_tca;
static i2s_chan_handle_t s_tx, s_rx;
static esp_codec_dev_handle_t s_spk, s_mic;

// ---- TCA9555 (registri: 0x02/0x03 output, 0x06/0x07 config; 1 = input) ----
static esp_err_t tca_write(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_tca, buf, sizeof(buf), 100);
}

esp_err_t audio_pa_enable(bool on)
{
    return tca_write(0x03, on ? 0x01 : 0x00);   // port1 bit0 = PA_CTRL
}

static esp_err_t tca_init(void)
{
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BOARD_TCA9555_ADDR,
        .scl_speed_hz = 400000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_i2c, &dev, &s_tca), TAG, "tca add");
    ESP_RETURN_ON_ERROR(tca_write(0x03, 0x00), TAG, "tca out");   // PA spento
    ESP_RETURN_ON_ERROR(tca_write(0x07, 0xFE), TAG, "tca cfg");   // port1 bit0 output
    return ESP_OK;
}

static esp_err_t i2s_init(void)
{
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.auto_clear_after_cb = true;
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan, &s_tx, &s_rx), TAG, "i2s chan");

    i2s_std_config_t std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = BOARD_I2S_MCLK,
            .bclk = BOARD_I2S_BCLK,
            .ws   = BOARD_I2S_WS,
            .dout = BOARD_I2S_DOUT,
            .din  = BOARD_I2S_DIN,
        },
    };
    std.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx, &std), TAG, "tx init");
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std), TAG, "rx init");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_tx), TAG, "tx en");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_rx), TAG, "rx en");
    return ESP_OK;
}

esp_err_t audio_init(void)
{
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = BOARD_I2C_SDA,
        .scl_io_num = BOARD_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus, &s_i2c), TAG, "i2c bus");
    ESP_RETURN_ON_ERROR(tca_init(), TAG, "tca");
    ESP_RETURN_ON_ERROR(i2s_init(), TAG, "i2s");

    audio_codec_i2s_cfg_t i2s_cfg = { .port = I2S_NUM_0, .rx_handle = s_rx, .tx_handle = s_tx };
    const audio_codec_data_if_t *data_if = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_RETURN_ON_FALSE(data_if, ESP_FAIL, TAG, "i2s data if");

    // ES8311 (DAC / speaker)
    audio_codec_i2c_cfg_t c8311 = { .port = I2C_NUM_0, .addr = BOARD_ES8311_ADDR, .bus_handle = s_i2c };
    const audio_codec_ctrl_if_t *ctrl8311 = audio_codec_new_i2c_ctrl(&c8311);
    const audio_codec_gpio_if_t *gpio_if = audio_codec_new_gpio();
    es8311_codec_cfg_t es8311 = {
        .ctrl_if = ctrl8311,
        .gpio_if = gpio_if,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .pa_pin = -1,            // PA gestito via TCA9555
        .use_mclk = true,
        .hw_gain = { .pa_voltage = 5.0, .codec_dac_voltage = 3.3 },
    };
    const audio_codec_if_t *codec8311 = es8311_codec_new(&es8311);
    ESP_RETURN_ON_FALSE(codec8311, ESP_FAIL, TAG, "ES8311 non risponde");
    esp_codec_dev_cfg_t spk_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT, .codec_if = codec8311, .data_if = data_if,
    };
    s_spk = esp_codec_dev_new(&spk_cfg);

    // ES7210 (ADC / microfoni)
    audio_codec_i2c_cfg_t c7210 = { .port = I2C_NUM_0, .addr = BOARD_ES7210_ADDR, .bus_handle = s_i2c };
    const audio_codec_ctrl_if_t *ctrl7210 = audio_codec_new_i2c_ctrl(&c7210);
    es7210_codec_cfg_t es7210 = {
        .ctrl_if = ctrl7210,
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2,
    };
    const audio_codec_if_t *codec7210 = es7210_codec_new(&es7210);
    ESP_RETURN_ON_FALSE(codec7210, ESP_FAIL, TAG, "ES7210 non risponde");
    esp_codec_dev_cfg_t mic_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN, .codec_if = codec7210, .data_if = data_if,
    };
    s_mic = esp_codec_dev_new(&mic_cfg);
    ESP_RETURN_ON_FALSE(s_spk && s_mic, ESP_FAIL, TAG, "codec dev");

    esp_codec_dev_sample_info_t fs = {
        .sample_rate = AUDIO_SAMPLE_RATE, .channel = 2, .bits_per_sample = 16,
    };
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_spk, &fs) == ESP_CODEC_DEV_OK, ESP_FAIL, TAG, "open spk");
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_mic, &fs) == ESP_CODEC_DEV_OK, ESP_FAIL, TAG, "open mic");
    esp_codec_dev_set_out_vol(s_spk, CONFIG_SS_VOLUME);
    esp_codec_dev_set_in_gain(s_mic, 37);
    ESP_LOGI(TAG, "Codec ES8311 + ES7210 inizializzati (%d Hz)", AUDIO_SAMPLE_RATE);
    return ESP_OK;
}

esp_codec_dev_handle_t audio_speaker(void) { return s_spk; }
esp_codec_dev_handle_t audio_mic(void) { return s_mic; }
