#ifndef APP_H
#define APP_H

#include "main.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 应用初始化：传入用于 OLED 的 I2C 句柄（例如 &hi2c1） */
void app_init(I2C_HandleTypeDef* i2c_for_oled);

/* 应用循环处理：包含 UWB 处理、发现/校准调度与 OLED 刷新 */
void app_process(void);

/* 底层上报：标签到各锚点的距离（单位：米）。anchor_ids 与 distances_m 一一对应，count 为条目数。 */
void app_on_tag_ranges(uint32_t count, const uint32_t* anchor_ids);

#ifdef __cplusplus
}
#endif

#endif /* APP_H */
