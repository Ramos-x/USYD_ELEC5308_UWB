#include "main.h"
#include "OLED/oled.h"
#include "OLED/font5x7.h"
#include <string.h>

#ifndef OLED_I2C_TIMEOUT
#define OLED_I2C_TIMEOUT  100
#endif

static I2C_HandleTypeDef* s_hi2c = NULL;
/* 128x64 -> 1024 字节显存缓存（页寻址，每页8行） */
static uint8_t s_Buffer[OLED_WIDTH * OLED_HEIGHT / 8];

/* 发送单字节命令 */
static inline HAL_StatusTypeDef oled_write_cmd(uint8_t cmd) {
    uint8_t buf[2] = {0x00, cmd}; /* 控制字节 0x00 表示命令 */
    return HAL_I2C_Master_Transmit(s_hi2c, (OLED_I2C_ADDR << 1), buf, sizeof(buf), OLED_I2C_TIMEOUT);
}

/* 发送数据块（自动加 0x40 控制字节，按 16 字节分包） */
static inline HAL_StatusTypeDef oled_write_data(const uint8_t* data, size_t size) {
    HAL_StatusTypeDef res = HAL_OK;
    uint8_t tmp[1 + 16];
    tmp[0] = 0x40; /* 控制字节 0x40 表示数据 */
    while (size) {
        uint8_t chunk = (size > 16) ? 16 : (uint8_t)size;
        memcpy(&tmp[1], data, chunk);
        res = HAL_I2C_Master_Transmit(s_hi2c, (OLED_I2C_ADDR << 1), tmp, (uint16_t)(1 + chunk), OLED_I2C_TIMEOUT);
        if (res != HAL_OK) return res;
        data += chunk;
        size -= chunk;
    }
    return res;
}

void OLED_SetI2C(I2C_HandleTypeDef* hi2c) {
    s_hi2c = hi2c;
}

void OLED_SetContrast(uint8_t contrast) {
    oled_write_cmd(0x81);
    oled_write_cmd(contrast);
}

void OLED_Init(I2C_HandleTypeDef *hi2c) {
    s_hi2c = hi2c;
    HAL_Delay(100);

    /* SSD1306 初始化序列（128x64） */
    oled_write_cmd(0xAE);             /* Display OFF */
    oled_write_cmd(0x20); oled_write_cmd(0x00); /* Memory Addressing Mode: Horizontal */
    oled_write_cmd(0xB0);             /* Page start address */
    oled_write_cmd(0xC8);             /* COM Output Scan Direction remapped */
    oled_write_cmd(0x00);             /* Low column address */
    oled_write_cmd(0x10);             /* High column address */
    oled_write_cmd(0x40);             /* Start line address */
    oled_write_cmd(0x81); oled_write_cmd(0x7F); /* Contrast */
    oled_write_cmd(0xA1);             /* Segment re-map 0 to 127 */
    oled_write_cmd(0xA6);             /* Normal display */
    oled_write_cmd(0xA8); oled_write_cmd(0x3F); /* Multiplex ratio(1 to 64) */
    oled_write_cmd(0xA4);             /* Output follows RAM content */
    oled_write_cmd(0xD3); oled_write_cmd(0x00); /* Display offset */
    oled_write_cmd(0xD5); oled_write_cmd(0x80); /* Display clock divide ratio/oscillator freq */
    oled_write_cmd(0xD9); oled_write_cmd(0xF1); /* Pre-charge period */
    oled_write_cmd(0xDA); oled_write_cmd(0x12); /* COM pins hardware configuration */
    oled_write_cmd(0xDB); oled_write_cmd(0x40); /* VCOMH deselect level */
    oled_write_cmd(0x8D); oled_write_cmd(0x14); /* Charge Pump enable */
    oled_write_cmd(0xAF);             /* Display ON */

    OLED_Clear();
    OLED_Update();
}

void OLED_Clear(void) {
    memset(s_Buffer, 0x00, sizeof(s_Buffer));
}

/* 设置一个像素 */
static void set_pixel(uint8_t x, uint8_t y, OLED_Color color) {
    if (x >= OLED_WIDTH || y >= OLED_HEIGHT) return;
    uint16_t index = x + (y / 8U) * OLED_WIDTH;
    uint8_t mask = (uint8_t)(1U << (y & 7U));
    if (color == OLED_COLOR_WHITE) {
        s_Buffer[index] |= mask;
    } else {
        s_Buffer[index] &= (uint8_t)~mask;
    }
}

/* 5x7 ASCII 字符绘制，行高 7，列宽 5，列间空 1 */
void OLED_DrawChar(uint8_t x, uint8_t y, char c) {
    if (c < 32 || c > 126) c = '?';
    const uint8_t* glyph = font5x7[(uint8_t)c - 32];
    for (uint8_t col = 0; col < 5; col++) {
        uint8_t bits = glyph[col];
        for (uint8_t row = 0; row < 7; row++) {
            OLED_Color color = (bits & (1U << row)) ? OLED_COLOR_WHITE : OLED_COLOR_BLACK;
            set_pixel((uint8_t)(x + col), (uint8_t)(y + row), color);
        }
    }
    /* 空一列做间隔 */
    for (uint8_t row = 0; row < 7; row++) {
        set_pixel((uint8_t)(x + 5), (uint8_t)(y + row), OLED_COLOR_BLACK);
    }
}

/* 显示字符串（不换行） */
void OLED_ShowString(uint8_t x, uint8_t y, const char* str) {
    uint8_t curX = x;
    while (str && *str) {
        if ((uint16_t)curX + 6U > OLED_WIDTH) break; /* 边缘截断 */
        OLED_DrawChar(curX, y, *str++);
        curX = (uint8_t)(curX + 6U);
    }
}

/* 刷新显存到屏幕（按页写入） */
void OLED_Update(void) {
    for (uint8_t page = 0; page < (OLED_HEIGHT / 8U); page++) {
        oled_write_cmd((uint8_t)(0xB0 | page)); /* Page address */
        oled_write_cmd(0x00);                   /* Low column */
        oled_write_cmd(0x10);                   /* High column */
        oled_write_data(&s_Buffer[OLED_WIDTH * page], OLED_WIDTH);
    }
}

/* 显示整数（右对齐） */
void OLED_ShowInt(uint8_t x, uint8_t y, int32_t value, uint8_t width) {
    char buf[16];
    int len = snprintf(buf, sizeof(buf), "%ld", (long)value);
    if (len < 0) return;

    /* 右对齐：计算起始位置 */
    int pad = (int)width - len;
    if (pad < 0) pad = 0;

    uint8_t curX = x;
    /* 前置空格 */
    for (int i = 0; i < pad; i++) {
        OLED_DrawChar(curX, y, ' ');
        curX += 6;
    }
    /* 显示数字 */
    OLED_ShowString(curX, y, buf);
}

/* 显示浮点数（右对齐） */
void OLED_ShowFloat(uint8_t x, uint8_t y, float value, uint8_t width, uint8_t decimals) {
    char buf[16];
    char fmt[8];
    snprintf(fmt, sizeof(fmt), "%%.%df", decimals);
    int len = snprintf(buf, sizeof(buf), fmt, (double)value);
    if (len < 0) return;

    /* 右对齐 */
    int pad = (int)width - len;
    if (pad < 0) pad = 0;

    uint8_t curX = x;
    for (int i = 0; i < pad; i++) {
        OLED_DrawChar(curX, y, ' ');
        curX += 6;
    }
    OLED_ShowString(curX, y, buf);
}

/* 画水平线 */
void OLED_DrawHLine(uint8_t x, uint8_t y, uint8_t width) {
    for (uint8_t i = 0; i < width; i++) {
        set_pixel((uint8_t)(x + i), y, OLED_COLOR_WHITE);
    }
}

/* 画垂直线 */
void OLED_DrawVLine(uint8_t x, uint8_t y, uint8_t height) {
    for (uint8_t i = 0; i < height; i++) {
        set_pixel(x, (uint8_t)(y + i), OLED_COLOR_WHITE);
    }
}

/* 画矩形框 */
void OLED_DrawRect(uint8_t x, uint8_t y, uint8_t width, uint8_t height) {
    OLED_DrawHLine(x, y, width);
    OLED_DrawHLine(x, (uint8_t)(y + height - 1), width);
    OLED_DrawVLine(x, y, height);
    OLED_DrawVLine((uint8_t)(x + width - 1), y, height);
}

/* 填充矩形 */
void OLED_FillRect(uint8_t x, uint8_t y, uint8_t width, uint8_t height, OLED_Color color) {
    for (uint8_t j = 0; j < height; j++) {
        for (uint8_t i = 0; i < width; i++) {
            set_pixel((uint8_t)(x + i), (uint8_t)(y + j), color);
        }
    }
}

/* 反转显示区域 */
void OLED_InvertArea(uint8_t x, uint8_t y, uint8_t width, uint8_t height) {
    for (uint8_t j = 0; j < height; j++) {
        for (uint8_t i = 0; i < width; i++) {
            uint8_t px = (uint8_t)(x + i);
            uint8_t py = (uint8_t)(y + j);
            if (px >= OLED_WIDTH || py >= OLED_HEIGHT) continue;
            uint16_t index = px + (py / 8U) * OLED_WIDTH;
            uint8_t mask = (uint8_t)(1U << (py & 7U));
            s_Buffer[index] ^= mask;  /* XOR 实现反转 */
        }
    }
}
