#ifndef OLED_H
#define OLED_H

#include <stdint.h>
#include "main.h"  /* 获取 HAL 定义的 I2C_HandleTypeDef */

#ifdef __cplusplus
extern "C" {
#endif

#define OLED_WIDTH   128
#define OLED_HEIGHT  64
#define OLED_I2C_ADDR 0x3C /* 常见 0.96 寸 SSD1306 I2C 地址：0x3C（7-bit） */

typedef enum {
    OLED_COLOR_BLACK = 0,
    OLED_COLOR_WHITE = 1
} OLED_Color;

/* 初始化：传入使用的 I2C 句柄（例如 &hi2c1 或 &hi2c2） */
void OLED_Init(I2C_HandleTypeDef* hi2c);

/* 切换 I2C 句柄（如需在运行时更换 I2C 总线） */
void OLED_SetI2C(I2C_HandleTypeDef* hi2c);

/* 清屏（清空显存缓存） */
void OLED_Clear(void);

/* 将显存缓存刷新到屏幕 */
void OLED_Update(void);

/* 对比度（0x00~0xFF） */
void OLED_SetContrast(uint8_t contrast);

/* 画单个 5x7 字符（x:0~127, y:0~63） */
void OLED_DrawChar(uint8_t x, uint8_t y, char c);

/* 显示 ASCII 字符串（不换行，超出边界自动截断） */
void OLED_ShowString(uint8_t x, uint8_t y, const char* str);

/* 显示整数（右对齐，width 指定宽度，不足补空格） */
void OLED_ShowInt(uint8_t x, uint8_t y, int32_t value, uint8_t width);

/* 显示浮点数（右对齐，width 指定总宽度，decimals 指定小数位数） */
void OLED_ShowFloat(uint8_t x, uint8_t y, float value, uint8_t width, uint8_t decimals);

/* 画水平线 */
void OLED_DrawHLine(uint8_t x, uint8_t y, uint8_t width);

/* 画垂直线 */
void OLED_DrawVLine(uint8_t x, uint8_t y, uint8_t height);

/* 画矩形框 */
void OLED_DrawRect(uint8_t x, uint8_t y, uint8_t width, uint8_t height);

/* 填充矩形 */
void OLED_FillRect(uint8_t x, uint8_t y, uint8_t width, uint8_t height, OLED_Color color);

/* 反转显示区域（用于高亮） */
void OLED_InvertArea(uint8_t x, uint8_t y, uint8_t width, uint8_t height);

#ifdef __cplusplus
}
#endif

#endif /* OLED_H */
