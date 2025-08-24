#include <stdio.h>
#include <string.h>
#include "stm32f1xx_hal.h"
#include "main.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "bu03.h"
#include "tag.h"
#include "app.h"
#include "OLED/oled.h"

/* 距离换算常量（DW 时基） */
#ifndef DWT_TIME_UNITS
#define DWT_TIME_UNITS (1.0/ (499.2e6 * 128.0))
#endif
#ifndef SPEED_OF_LIGHT
#define SPEED_OF_LIGHT 299702547.0
#endif

/* 最近一次 POLL 的 TX 时间戳（40bit，放入 64bit） */
static volatile uint64_t g_last_poll_tx_ts = 0;

/* UART1 由 CubeMX 生成于 main.c */
extern UART_HandleTypeDef huart1;

/* 网络参数：PAN 与短地址（示例值，可按需修改） */
static uint16_t g_pan_id = 0xDECA;
static uint16_t g_tag_short = 0x1234;
static const uint16_t g_broadcast_short = 0xFFFF;

/* 频率节流（TAG 发送 POLL 的频率） */
static volatile uint32_t g_min_interval_ms = 500;
static volatile uint32_t g_last_tx_ms = 0;
static volatile uint32_t g_last_flush_ms = 0;

/* 基于芯片唯一ID生成16位短地址，保证不同设备不会重复 */
void tag_randomize_short(void)
{
    /* 使用 HAL 提供的 UID 接口，兼容不同芯片封装 */
    uint32_t u0 = HAL_GetUIDw0();
    uint32_t u1 = HAL_GetUIDw1();
    uint32_t u2 = HAL_GetUIDw2();

    /* FNV-1a 风格混合，分布稳定，碰撞概率低 */
    uint32_t mix = 2166136261u;        /* FNV offset basis */
    mix ^= u0; mix *= 16777619u;       /* FNV prime */
    mix ^= u1; mix *= 16777619u;
    mix ^= u2; mix *= 16777619u;

    /* 折叠为 16 位 */
    uint16_t id = (uint16_t)((mix ^ (mix >> 16)) & 0xFFFFu);

    /* 避开保留地址（0x0000、0xFFFF 和广播地址） */
    if (id == 0x0000u || id == 0xFFFFu || id == g_broadcast_short) {
        id ^= 0xA5A5u;
        if (id == 0x0000u || id == 0xFFFFu) {
            id ^= 0x1D0Fu;
        }
    }

    g_tag_short = id;
}

/* 提供对外读取 Tag 短地址的接口 */
uint16_t tag_get_short(void)
{
    return g_tag_short;
}


/* 聚合 ANCHOR 信息 */
typedef struct {
    uint16_t id;
    uint8_t ts[5]; /* 40-bit RX timestamp from anchor payload */
    float dist_m;  /* 单边 TWR 计算得到的距离（米） */
    uint32_t last_tick;
    uint8_t updated;
} anchor_info_t;

#define MAX_ANCHORS 16
static anchor_info_t g_anchors[MAX_ANCHORS];

/* 小工具：查找/插入 anchor 项 */
static anchor_info_t *find_or_alloc_anchor(uint16_t id) {
    int free_idx = -1;
    for (int i = 0; i < MAX_ANCHORS; ++i) {
        if (g_anchors[i].id == id) {
            return &g_anchors[i];
        }
        if (free_idx < 0 && g_anchors[i].id == 0) {
            free_idx = i;
        }
    }
    if (free_idx >= 0) {
        g_anchors[free_idx].id = id;
        return &g_anchors[free_idx];
    }
    return NULL; /* 满了则丢弃 */
}

/* HEX 辅助 */
static inline char hex4(uint8_t v) {
    v &= 0x0F;
    return (char) ((v < 10) ? ('0' + v) : ('A' + (v - 10)));
}

/* UART 输出一行 */
static void uart1_println(const char *s) {
    size_t n = strlen(s);
    HAL_UART_Transmit(&huart1, (uint8_t *) s, (uint16_t) n, 100);
    const char crlf[2] = {'\r', '\n'};
    HAL_UART_Transmit(&huart1, (uint8_t *) crlf, 2, 100);
}

/* 组帧并发送 POLL（目的地址广播，从而所有 ANCHOR 可响应） */
static void tag_try_tx_poll(void) {
    uint32_t now = HAL_GetTick();
    if ((now - g_last_tx_ms) < g_min_interval_ms) {
        return;
    }

    uint8_t tx[32];
    uint8_t i = 0;
    tx[i++] = 0x41;
    tx[i++] = 0x88; /* Data + short addr + PAN 压缩 */
    tx[i++] = (uint8_t) (now & 0xFF); /* 简单序列 */
    tx[i++] = (uint8_t) (g_pan_id & 0xFF);
    tx[i++] = (uint8_t) (g_pan_id >> 8);
    /* 目的地址 -> 广播 */
    tx[i++] = (uint8_t) (g_broadcast_short & 0xFF);
    tx[i++] = (uint8_t) (g_broadcast_short >> 8);
    /* 源地址 -> 本 TAG */
    tx[i++] = (uint8_t) (g_tag_short & 0xFF);
    tx[i++] = (uint8_t) (g_tag_short >> 8);
    tx[i++] = 'P';
    tx[i++] = 'O';
    tx[i++] = 'L';
    tx[i++] = 'L';

    uint16_t txlen = i;
    if (dwt_writetxdata(txlen, tx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(txlen, 0, 1); /* ranging=1 */
        (void) dwt_starttx(DWT_START_TX_IMMEDIATE | DWT_RESPONSE_EXPECTED);
        g_last_tx_ms = now;
    }
}

/* 回调：TX 完成后确保回到接收 */
static void cb_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;
    /* 读取本次发射的 40bit 时间戳并缓存（用于 TWR） */
    uint8_t txts5[5];
    dwt_readtxtimestamp(txts5);
    uint64_t t = 0;
    for (int k = 0; k < 5; ++k) {
        t |= ((uint64_t)txts5[k]) << (8 * k);
    }
    g_last_poll_tx_ts = t;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* 回调：接收错误/超时后继续接收 */
static void cb_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void cb_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* 回调：接收 RSP，解析 Anchor 的 RX/TX 时间戳并计算距离（单边 TWR） */
static void cb_rx_ok(const dwt_cb_data_t *cb) {
    uint8_t rxbuf[127];
    uint16_t rxlen = cb->datalength;
    if (rxlen > sizeof(rxbuf)) rxlen = sizeof(rxbuf);
    dwt_readrxdata(rxbuf, rxlen, 0);

    /* 检查 RSP 标识：至少包含 'R''S''P' + rx_ts[5] + tx_ts[5] */
    if (rxlen >= 22 && rxbuf[9] == 'R' && rxbuf[10] == 'S' && rxbuf[11] == 'P') {
        uint16_t anchor_id = (uint16_t) rxbuf[7] | ((uint16_t) rxbuf[8] << 8);
        anchor_info_t *e = find_or_alloc_anchor(anchor_id);
        if (e) {
            /* 提取 Anchor 的 RX(T_poll) 与计划 TX(T_rsp) 的 40bit 时间戳 */
            uint64_t t_rx1 = 0, t_tx2 = 0;
            for (int k = 0; k < 5; ++k) t_rx1 |= ((uint64_t)rxbuf[12 + k]) << (8 * k);
            for (int k = 0; k < 5; ++k) t_tx2 |= ((uint64_t)rxbuf[17 + k]) << (8 * k);
            for (int k = 0; k < 5; ++k) e->ts[k] = rxbuf[12 + k];

            /* 读取本地接收时间戳 T_rx2（40bit） */
            uint8_t rxts5[5];
            dwt_readrxtimestamp(rxts5);
            uint64_t t_rx2 = 0;
            for (int k = 0; k < 5; ++k) t_rx2 |= ((uint64_t)rxts5[k]) << (8 * k);

            /* 计算单边 TWR: ToF = ((T_rx2 - T_tx1) - (T_tx2 - T_rx1)) / 2 */
            const uint64_t TS_MASK_40 = 0xFFFFFFFFFFULL;
            uint64_t t_tx1 = g_last_poll_tx_ts & TS_MASK_40;
            uint64_t tround = (t_rx2 - t_tx1) & TS_MASK_40;
            uint64_t treply = (t_tx2 - t_rx1) & TS_MASK_40;

            double tof_dtu = 0.5 * (double)((int64_t)tround - (int64_t)treply);
            if (tof_dtu < 0) tof_dtu = 0;
            double distance_m = tof_dtu * DWT_TIME_UNITS * SPEED_OF_LIGHT;

            e->dist_m = (float)distance_m;
            e->last_tick = HAL_GetTick();
            e->updated = 1;
        }
    }

    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* 定时输出 JSON：聚合最近一次 POLL 周期内收到的所有 ANCHOR 响应，并上报给应用层 */
static void try_flush_json(void) {
    uint32_t now = HAL_GetTick();
    if ((now - g_last_flush_ms) < g_min_interval_ms) {
        return;
    }

    /* 检查是否有更新的 anchor */
    int has_any = 0;
    for (int i = 0; i < MAX_ANCHORS; ++i) {
        if (g_anchors[i].id != 0 && g_anchors[i].updated) {
            has_any = 1;
            break;
        }
    }
    if (!has_any) {
        g_last_flush_ms = now;
        return;
    }

    /* 先准备应用层上报数据 */
    uint32_t ids[16];
    float dists[16];
    uint32_t cnt = 0;

    char out[512];
    size_t pos = 0;
    int n;

    n = snprintf(out + pos, sizeof(out) - pos,
                 "{\"role\":\"tag\",\"tag\":%u,\"tick\":%lu,\"anchors\":[",
                 (unsigned) g_tag_short, (unsigned long) now);
    if (n < 0) return;
    pos += (size_t) n;

    int first = 1;
    for (int i = 0; i < MAX_ANCHORS; ++i) {
        if (g_anchors[i].id == 0 || !g_anchors[i].updated) continue;

        if (!first) {
            if (pos < sizeof(out)) out[pos++] = ',';
        }
        first = 0;

        /* ts 转 hex 字符串（10 hex） */
        char ts_hex[11];
        for (int k = 0; k < 5; ++k) {
            ts_hex[k * 2] = hex4(g_anchors[i].ts[k] >> 4);
            ts_hex[k * 2 + 1] = hex4(g_anchors[i].ts[k]);
        }
        ts_hex[10] = '\0';

        n = snprintf(out + pos, sizeof(out) - pos,
                     "{\"id\":%u,\"ts\":\"%s\",\"tick\":%lu,\"dist\":%.2f}",
                     (unsigned) g_anchors[i].id, ts_hex, (unsigned long) g_anchors[i].last_tick,
                     (double)g_anchors[i].dist_m);
        if (n < 0) break;
        pos += (size_t) n;

        /* 汇总用于应用层 */
        if (cnt < 16) {
            ids[cnt] = g_anchors[i].id;
            dists[cnt] = g_anchors[i].dist_m;
            cnt++;
        }

        /* 清除 updated 标志，等待下个周期 */
        g_anchors[i].updated = 0;
    }

    if (pos < sizeof(out)) out[pos++] = ']';
    if (pos < sizeof(out)) out[pos++] = '}';

    /* 结尾并输出 */
    out[(pos < sizeof(out)) ? pos : (sizeof(out) - 1)] = '\0';
    uart1_println(out);

    /* 上报给应用层（用于 UI 与后续定位） */
    if (cnt > 0) {
        app_on_tag_ranges(cnt, ids, dists);
    }

    g_last_flush_ms = now;
}

void tag_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms = (uint32_t) (1000.0f / rate + 0.5f);
}

void tag_init(void) {
    /* 设置 PAN 与短地址 */
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_tag_short);

    /* 在 OLED 上显示 TAG 短地址（HEX） */
    {
        char buf[16];
        (void)snprintf(buf, sizeof(buf), "TAG:%04X", (unsigned)g_tag_short);
        /* 放在第二行，避免与头部信息重叠；如需调整位置可修改坐标 */
        OLED_ShowString(64, 8, buf);
        OLED_Update();
    }

    /* 注册 TAG 回调并使能关键中断 */
    dwt_setcallbacks(cb_tx_done, cb_rx_ok, cb_rx_to, cb_rx_err, NULL, NULL);
    dwt_setinterrupt(DWT_INT_RFCG | DWT_INT_TFRS, 0, DWT_ENABLE_INT);

    /* 持续接收 */
    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    /* 清空表 */
    memset(g_anchors, 0, sizeof(g_anchors));
    g_last_tx_ms = g_last_flush_ms = HAL_GetTick();
}

void tag_process(void) {
    /* 轮询转发 ISR（辅以外部中断） */
    if (dwt_checkirq()) {
        dwt_isr();
    }
    tag_try_tx_poll();
    try_flush_json();
}
