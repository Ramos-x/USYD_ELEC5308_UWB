#include "main.h"
#include "bu03.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "tag.h"
#include "anchor.h"

/* 默认定位频率（Hz） */
#ifndef BU03_RATE_HZ_DEFAULT
#define BU03_RATE_HZ_DEFAULT 10.0f
#endif

static float s_rate_hz = BU03_RATE_HZ_DEFAULT;
static int   s_init_ok = 0;
static int   s_last_err = 0;
/* 运行时角色：由 PB2(BOOT1) 决定，0=Anchor, 1=Tag（上拉为1即Tag） */
static int   s_role;

void bu03_reset(void) {
    /* 仅重置运行时状态，角色在 init 中读取硬件后确定 */
    s_init_ok  = 0;
    s_last_err = 0;
    s_rate_hz  = BU03_RATE_HZ_DEFAULT;
}

int bu03_init(void) {
    /* 已初始化则直接返回成功 */
    if (s_init_ok) {
        return 0;
    }
    bu03_reset();

    /* 读取 PB2(BOOT1) 确定角色：0->Anchor，1->Tag */
    GPIO_PinState pin = HAL_GPIO_ReadPin(BOOT1_GPIO_Port, BOOT1_Pin);
    s_role = (pin == GPIO_PIN_RESET) ? BU03_ROLE_ANCHOR : BU03_ROLE_TAG;

    /* 通用 UWB 初始化 */
    const int rc = UWB_DW3000_Init();
    if (rc != 0) {
        s_last_err = rc;  /* 记录底层返回的具体错误码 */
        return rc;        /* 直接把错误码返回给上层 */
    }

    /* 按角色初始化 */
    if (s_role == BU03_ROLE_ANCHOR) {
        /* 先随机化短地址，确保可能的首次发送前已生效 */
        anchor_randomize_short();
        anchor_init();
    } else {
        /* 先随机化短地址，确保可能的首次发送前已生效 */
        tag_randomize_short();
        tag_init();
    }

    /* 设置默认频率 */
    bu03_set_rate_hz(BU03_RATE_HZ_DEFAULT);

    s_init_ok = 1;
    s_last_err = 0;
    return 0;
}

void bu03_process(void) {
    if (s_role == BU03_ROLE_ANCHOR) {
        anchor_process();
    } else {
        tag_process();
    }
}

void bu03_set_rate_hz(float rate) {
    s_rate_hz = rate;
    if (s_role == BU03_ROLE_ANCHOR) {
        anchor_set_rate_hz(20.0f);
    } else {
        tag_set_rate_hz(rate);
    }
}

int bu03_is_ready(void) { return s_init_ok; }
int bu03_get_last_error(void) { return s_last_err; }

float bu03_get_rate_hz(void) { return s_rate_hz; }
int bu03_get_role(void) { return s_role; }
