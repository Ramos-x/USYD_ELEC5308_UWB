#include "main.h"
#include "bu03.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "tag.h"
#include "anchor.h"

/* 默认定位频率（Hz） */
#ifndef BU03_RATE_HZ_DEFAULT
#define BU03_RATE_HZ_DEFAULT 2.0f
#endif

static float s_rate_hz = BU03_RATE_HZ_DEFAULT;
static int   s_init_ok = 0;
static int   s_last_err = 0;

int bu03_init(void) {
    /* 已初始化则直接返回成功 */
    if (s_init_ok) {
        return 0;
    }

    s_init_ok  = 0;
    s_last_err = 0;

    /* 通用 UWB 初始化 */
    int rc = UWB_DW3000_Init();
    if (rc != 0) {
        s_last_err = rc;  /* 记录底层返回的具体错误码 */
        return rc;        /* 直接把错误码返回给上层 */
    }

#if BU03_ROLE == BU03_ROLE_ANCHOR
    anchor_init();
#else
    tag_init();
#endif

    /* 设置默认频率 */
    bu03_set_rate_hz(BU03_RATE_HZ_DEFAULT);

    s_init_ok = 1;
    s_last_err = 0;
    return 0;
}

void bu03_process(void) {
#if BU03_ROLE == BU03_ROLE_ANCHOR
    anchor_process();
#else
    tag_process();
#endif
}

void bu03_set_rate_hz(float rate) {
    s_rate_hz = rate;
#if BU03_ROLE == BU03_ROLE_ANCHOR
    anchor_set_rate_hz(rate);
#else
    tag_set_rate_hz(rate);
#endif
}

int bu03_is_ready(void) { return s_init_ok; }
int bu03_get_last_error(void) { return s_last_err; }

float bu03_get_rate_hz(void) { return s_rate_hz; }
int bu03_get_role(void) { return BU03_ROLE; }
