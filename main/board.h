#pragma once
// Pin mapping Waveshare ESP32-S3-AUDIO-Board
#define BOARD_I2C_SDA     11
#define BOARD_I2C_SCL     10
#define BOARD_I2S_MCLK    12
#define BOARD_I2S_BCLK    13
#define BOARD_I2S_WS      14
#define BOARD_I2S_DIN     15   // mic (ES7210 -> ESP32)
#define BOARD_I2S_DOUT    16   // speaker (ESP32 -> ES8311)
#define BOARD_RGB_GPIO    38

#define BOARD_ES8311_ADDR 0x30  // 8-bit (0x18 7-bit)
#define BOARD_ES7210_ADDR 0x80  // 8-bit (0x40 7-bit)
#define BOARD_TCA9555_ADDR 0x20 // 7-bit
#define BOARD_EXIO_PA_CTRL 8    // amplificatore NS4150B (TCA9555 port1 bit0)
