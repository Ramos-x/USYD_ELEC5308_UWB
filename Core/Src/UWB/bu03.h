//
// Created by ramos on 2025/8/20.
//

#ifndef UWB_TRANS_BU03_H
#define UWB_TRANS_BU03_H

#include "stm32f1xx_hal.h"

#ifdef __cplusplus
extern "C" {
#endif

/* BU03 角色宏：通过修改 BU03_ROLE 切换 Anchor/Tag */
#define BU03_ROLE_ANCHOR 1
#define BU03_ROLE_TAG    2
#ifndef BU03_ROLE
#define BU03_ROLE BU03_ROLE_TAG
#endif

/* 对外 API */
int  bu03_init(void);
void bu03_process(void);
void bu03_set_rate_hz(float rate);
/* 状态与查询 */
int  bu03_is_ready(void);
int  bu03_get_last_error(void);
/* 查询当前发送/测距频率（Hz）与角色（编译期宏） */
float bu03_get_rate_hz(void);
int bu03_get_role(void);

#ifdef __cplusplus
}
#endif

#endif //UWB_TRANS_BU03_H