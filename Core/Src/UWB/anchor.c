#include <stdio.h>
#include <string.h>
#include "stm32f1xx_hal.h"
#include "main.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "bu03.h"
#include "app.h"
#include "anchor.h"

#include "uwb_frames.h"
#include "OLED/oled.h"

/* 距离/时间常量与延迟应答配置 */
#ifndef DWT_TIME_UNITS
#define DWT_TIME_UNITS (1.0/ (499.2e6 * 128.0))
#endif
#define ANCHOR_REPLY_DELAY_US 3000U
#define REPLY_DELAY_DTU ((uint64_t)((ANCHOR_REPLY_DELAY_US * 1e-6) / DWT_TIME_UNITS + 0.5))

/* 网络参数：PAN 与短地址（示例值，可按需修改） */
static uint16_t g_pan_id = 0xDECA;
static uint16_t g_anchor_short = 0x5678;
static const uint16_t g_broadcast_short = 0xFFFF;

/* 限流：避免响应过于频繁 */
static volatile uint32_t g_min_interval_ms = 500;
static volatile uint32_t g_last_tx_ms = 0;

/* UART1 由 CubeMX 生成于 main.c */
extern UART_HandleTypeDef huart1;

/* 基于芯片唯一ID生成16位短地址，保证不同设备不会重复 */
void anchor_randomize_short(void) {
    /* 使用 HAL 提供的 UID 接口，兼容不同芯片封装 */
    uint32_t u0 = HAL_GetUIDw0();
    uint32_t u1 = HAL_GetUIDw1();
    uint32_t u2 = HAL_GetUIDw2();

    /* FNV-1a 风格混合，分布稳定，碰撞概率低 */
    uint32_t mix = 2166136261u; /* FNV offset basis */
    mix ^= u0;
    mix *= 16777619u; /* FNV prime */
    mix ^= u1;
    mix *= 16777619u;
    mix ^= u2;
    mix *= 16777619u;

    /* 折叠为 16 位 */
    uint16_t id = (uint16_t) ((mix ^ (mix >> 16)) & 0xFFFFu);

    /* 避开保留地址（0x0000、0xFFFF 和广播地址） */
    if (id == 0x0000u || id == 0xFFFFu || id == g_broadcast_short) {
        id ^= 0xA5A5u;
        if (id == 0x0000u || id == 0xFFFFu) {
            id ^= 0x1D0Fu;
        }
    }

    g_anchor_short = id;
}

/* 提供对外读取 anchor 短地址的接口 */
uint16_t anchor_get_short(void) {
    return g_anchor_short;
}

// ========== 用户回调 ==========
static volatile uint8_t s_tx_busy = 0;
/* 回调：TX 完成后回到接收 */
static void on_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;
    s_tx_busy = 0;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* 回调：接收错误/超时后继续接收 */
static void on_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;
    s_tx_busy = 0;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void on_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    s_tx_busy = 0; // 错误也释放
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void uart1_println(const char *s) {
    size_t n = strlen(s);
    HAL_UART_Transmit(&huart1, (uint8_t *) s, (uint16_t) n, 100);
    const char crlf[2] = {'\r', '\n'};
    HAL_UART_Transmit(&huart1, (uint8_t *) crlf, 2, 100);
}

/* 回调：收到 POLL 则回 RSP，负载携带 RX 时间戳（5 字节） */
static void on_rx_ok(const dwt_cb_data_t *cb) {
    uint8_t rxbuf[127];
    uint16_t rxlen = cb->datalength;
    if (rxlen > sizeof(rxbuf)) rxlen = sizeof(rxbuf);
    dwt_readrxdata(rxbuf, rxlen, 0);

    uwb_frame_view_t v;
    if (uwb_parse_frame(rxbuf, rxlen, &v) != 0) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }
    if (v.hdr->pan != g_pan_id || uwb_get_msg_type(&v) != UWB_MSG_POLL) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    /* 速率限制 */
    uint32_t now = HAL_GetTick();
    if ((now - g_last_tx_ms) < g_min_interval_ms) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    /* 时间戳：读取本帧的 RX 时间，计算计划的 TX 时间（延迟发送） */
    uint8_t rxts5[5];
    dwt_readrxtimestamp(rxts5);
    uint64_t t_rx1 = uwb_ts40_to_64(rxts5);
    uint64_t t_tx2 = t_rx1 + REPLY_DELAY_DTU;

    /* 组 RESP 帧（目的=发起方，源=本 Anchor） */
    uint8_t txbuf[64];
    uint16_t mac_len = uwb_build_resp(txbuf,
                                      (uint8_t) (v.hdr->seq + 1),
                                      v.hdr->pan,
                                      v.hdr->src, /* dest = tag  */
                                      g_anchor_short, /* src  = anchor */
                                      t_rx1, t_tx2);

    if (dwt_writetxdata(mac_len, txbuf, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(mac_len + 2, 0, 1);          /* +2 包含 FCS；rng=1 */
        dwt_setdelayedtrxtime((uint32_t)(t_tx2 >> 8));/* 仅写高 32 位 */
        if (dwt_starttx(DWT_START_TX_DELAYED) == DWT_SUCCESS) {
            g_last_tx_ms = now;
        } else {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        }
    } else {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
    }

    s_tx_busy = 0;
}

void anchor_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms = (uint32_t) (1000.0f / rate + 0.5f);
}

void anchor_init(void) {
    /* 设置 PAN 与 ANCHOR 短地址 */
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_anchor_short);

    /* 在 OLED 上显示 ANCHOR 短地址（HEX） */
    {
        char buf[16];
        (void) snprintf(buf, sizeof(buf), "ACR:%04X", (unsigned) g_anchor_short);
        /* 放在第二行，避免与头部信息重叠；如需调整位置可修改坐标 */
        OLED_ShowString(0, 8, buf);
    }

    /* 注册 ANCHOR 回调并使能关键中断 */
    dwt_setcallbacks(on_tx_done, on_rx_ok, on_rx_to, on_rx_err, NULL, NULL);
    dwt_setinterrupt(DWT_INT_RFCG | DWT_INT_TFRS, 0, DWT_ENABLE_INT);

    /* 持续接收 */
    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    g_last_tx_ms = HAL_GetTick();
}

void anchor_process(void) {}
