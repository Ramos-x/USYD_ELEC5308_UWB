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


#include <stdarg.h>
#include <stdlib.h>

/* ====== Anchor 时隙配置（与 Tag 共享一套参数更稳妥） ====== */
#define ANCHOR_ID_FIRST         0x0001
#define ANCHOR_ID_LAST          0x0005
#define ANCHOR_SLOT_COUNT       (ANCHOR_ID_LAST - ANCHOR_ID_FIRST + 1) /* =5 */

#define ANCHOR_SLOT_BASE_US     2500U   /* 槽0的 RESP 相对 POLL 的基准延迟 */
#define ANCHOR_SLOT_SPACING_US  2000U   /* 槽与槽之间的间隔（要大于一个RESP空口时长+裕量） */

/* Tag 会在收到 RESP ~2ms 后发 FINAL，Anchor 侧监听窗口要覆盖它 */
#define TAG_FINAL_DELAY_US      2000U   /* 与 Tag 侧保持一致 */
#define FINAL_CHAIN_GAP_US      800U    /* Tag 串行发 FINAL 的最小间隔（信息） */

/* Anchor 侧 FINAL 监听窗，足以覆盖 2ms 基准 + 稍许裕量即可
   因为我们让时隙间隔 (2000us) > FINAL_CHAIN_GAP_US (800us)，
   Tag 不会因为“前一个 FINAL”把“后一个 FINAL”往后挤。 */
#ifndef FINAL_WINDOW_US
#define FINAL_WINDOW_US         4000U
#endif


/* ================== 时基常量 ================== */
#ifndef DWT_TIME_UNITS
#define DWT_TIME_UNITS (1.0/(499.2e6*128.0))
#endif
#ifndef SPEED_OF_LIGHT
#define SPEED_OF_LIGHT 299702547.0
#endif
#ifndef US_TO_DTU
#define US_TO_DTU(us) ((uint64_t)(((us)*1e-6)/DWT_TIME_UNITS + 0.5))
#endif

#define TS_MASK_40 0xFFFFFFFFFFULL
#ifndef DTU_TO_US_I32
#define DTU_TO_US_I32(dtu64) ( (int32_t)((double)(dtu64)*DWT_TIME_UNITS*1e6 + 0.5) )
#endif
#ifndef DTU_TO_MM_I32
#define DTU_TO_MM_I32(dtu64) ( (int32_t)((double)(dtu64)*DWT_TIME_UNITS*299702547.0*1000.0 + 0.5) )
#endif
#ifndef DTU_TO_NS_I32
#define DTU_TO_NS_I32(dtu64) ( (int32_t)((double)(dtu64)*DWT_TIME_UNITS*1e9 + 0.5) )
#endif

#ifndef DTU_TO_NS_I64
#define DTU_TO_NS_I64(dtu64) ((int64_t)((double)(dtu64)*DWT_TIME_UNITS*1e9 + 0.5))
#endif
#ifndef DTU_TO_MM_I64
#define DTU_TO_MM_I64(dtu64) ((int64_t)((double)(dtu64)*DWT_TIME_UNITS*SPEED_OF_LIGHT*1000.0 + 0.5))
#endif

#define TS_MASK_40 0xFFFFFFFFFFULL
#define ANCHOR_REPLY_BASE_US     2500U      // 基准(首个Anchor)的延迟
#define ANCHOR_SLOT_SPACING_US   2000U      // 邻近两个Anchor之间的时隙间隔
#define NUM_ANCHOR_SLOTS         4          // 先给够，后面想扩到更多Anchor也行
static volatile uint8_t s_sending_resp = 0;
static volatile uint16_t s_resp_tag_pending = 0;

extern UART_HandleTypeDef huart1;
/* Anchor 回复 POLL 的固定延迟（你原有配置） */
#define ANCHOR_REPLY_DELAY_US 3000U
#define REPLY_DELAY_DTU       US_TO_DTU(ANCHOR_REPLY_DELAY_US)

/* Anchor 在回 RESP 之后等待 Tag 的 FINAL 的窗口（按 Tag 的 TAG_FINAL_DELAY_US 留裕量） */
#ifndef FINAL_WINDOW_US
#define FINAL_WINDOW_US 4000U   /* 可按实测调大/调小 */
#endif

/* ================== 网络参数 ================== */
static uint16_t g_pan_id = 0xDECA;
static uint16_t g_anchor_short = 0x0002;
static const uint16_t g_broadcast_short = 0xFFFF;

/* 节流：避免过快重复发 RESP（可保留） */
static volatile uint32_t g_min_interval_ms = 1;
static volatile uint32_t g_last_tx_ms = 0;

/* 最近一次 RESP 的计划发送时间戳（40bit->64）按 Tag 维度保存 */
typedef struct {
    uint16_t tag;
    uint8_t expect_seq; /* 期望收到的 FINAL 序号 = poll.seq + 2（8bit 回卷） */
    uint64_t t_rx1; /* 我方收到 POLL 的时刻 */
    uint64_t t_tx2; /* 我方计划发 RESP 的时刻（延迟 TX 时刻） */
    uint32_t tick; /* 开始时间用于过期清理 */
    uint8_t active;
} ds_sess_t;

#define SESS_CAP 8
static ds_sess_t s_sess[SESS_CAP];

static ds_sess_t *sess_find(uint16_t tag) {
    for (int i = 0; i < SESS_CAP; ++i) if (s_sess[i].active && s_sess[i].tag == tag) return &s_sess[i];
    return NULL;
}

static ds_sess_t *sess_get_or_alloc(uint16_t tag) {
    ds_sess_t *p = sess_find(tag);
    if (p) return p;
    for (int i = 0; i < SESS_CAP; ++i)
        if (!s_sess[i].active) {
            memset(&s_sess[i], 0, sizeof(s_sess[i]));
            s_sess[i].active = 1;
            s_sess[i].tag = tag;
            return &s_sess[i];
        }
    return NULL; /* 满了可直接复用最老的 */
}

static void sess_clear(uint16_t tag) {
    for (int i = 0; i < SESS_CAP; ++i)
        if (s_sess[i].active && s_sess[i].tag == tag) {
            s_sess[i].active = 0;
            break;
        }
}

/* 0x0001 -> slot 0, 0x0002 -> slot 1, ... 0x0005 -> slot 4
   超出范围的ID也能稳定落到 0..(ANCHOR_SLOT_COUNT-1) */
static inline uint8_t anchor_slot_index_from_id(uint16_t aid)
{
    if (aid < ANCHOR_ID_FIRST || aid > ANCHOR_ID_LAST)
        return (uint8_t)((aid - ANCHOR_ID_FIRST) % ANCHOR_SLOT_COUNT);
    return (uint8_t)(aid - ANCHOR_ID_FIRST);
}

static inline uint8_t anchor_slot_index(void)
{
    return anchor_slot_index_from_id(g_anchor_short);
}


/* ========== 地址工具 ========== */
/* 基于芯片唯一ID生成16位短地址，保证不同设备不会重复 */
void anchor_randomize_short(void) {
    uint32_t u0 = HAL_GetUIDw0(), u1 = HAL_GetUIDw1(), u2 = HAL_GetUIDw2();
    uint32_t mix = 2166136261u;
    mix ^= u0;
    mix *= 16777619u;
    mix ^= u1;
    mix *= 16777619u;
    mix ^= u2;
    mix *= 16777619u;
    uint16_t id = (uint16_t) ((mix ^ (mix >> 16)) & 0xFFFFu);
    if (id == 0x0000u || id == 0xFFFFu || id == g_broadcast_short) {
        id ^= 0xA5A5u;
        if (id == 0x0000u || id == 0xFFFFu) id ^= 0x1D0Fu;
    }
    // g_anchor_short = id;
    g_anchor_short = 0x0001;
}


uint16_t anchor_get_short(void) { return g_anchor_short; }

static void ts40_to_hex(char out[11], uint64_t ts40) {
    // 40bit 小端->HEX（高位在前）
    uint8_t b[5];
    for (int i = 0; i < 5; ++i) b[i] = (uint8_t) ((ts40 >> (8 * i)) & 0xFF);
    for (int i = 0; i < 5; ++i) sprintf(out + 2 * i, "%02X", b[4 - i]);
    out[10] = '\0';
}

// 相对微秒（先在40bit域内做差，再转us）
static inline int32_t rel_us(uint64_t newer, uint64_t older) {
    uint64_t d = (newer - older) & TS_MASK_40;
    return DTU_TO_US_I32(d); // <= 17,200,000 以内，int32 安全
}

/* ========== 回调 ========== */
static volatile uint8_t s_tx_busy = 0;

/* TX 完成：回 RX */
static void on_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;

    if (s_sending_resp) {
        uint8_t txts5[5];
        dwt_readtxtimestamp(txts5);
        uint64_t real_tx2 = uwb_ts40_to_64(txts5);

        ds_sess_t *sess = sess_find(s_resp_tag_pending);
        if (sess && sess->active) {
            int32_t plan_off_us = rel_us(sess->t_tx2, sess->t_rx1); // 计划延迟（应≈3000us）
            int32_t real_off_us = rel_us(real_tx2, sess->t_rx1); // 实际延迟

            char real_hex[11];
            ts40_to_hex(real_hex, real_tx2);
            uart1_printf("[RESP] tag=%u real_tx2=0x%s plan_off=%ldus real_off=%ldus",
                         (unsigned) s_resp_tag_pending, real_hex,
                         (long) plan_off_us, (long) real_off_us);

            sess->t_tx2 = real_tx2; // 用真实TX时间覆盖
        }
        s_sending_resp = 0;
    }

    s_tx_busy = 0;
}


/* RX 超时/错误：回 RX */
static void on_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;
    s_tx_busy = 0;

    // 可选：简单清理所有活跃会话（或按 tick 做精确过期）
    for (int i = 0; i < SESS_CAP; ++i) {
        if (s_sess[i].active) s_sess[i].active = 0;
    }

    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void on_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    s_tx_busy = 0;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* ========== RX 成功：处理 POLL 或 FINAL ========== */
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
    if (v.hdr->pan != g_pan_id) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    /* ---------- 处理 POLL ---------- */
    if (uwb_get_msg_type(&v) == UWB_MSG_POLL) {
        /* 节流（可选） */
        uint32_t now_ms = HAL_GetTick();
        if ((now_ms - g_last_tx_ms) < g_min_interval_ms) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }

        /* 我方收到 POLL 的时刻 T_rx1 */
        uint8_t rxts5[5];
        dwt_readrxtimestamp(rxts5);
        uint64_t t_rx1 = uwb_ts40_to_64(rxts5);


        uint8_t slot = anchor_slot_index();
        uint64_t delay_dtu = US_TO_DTU(ANCHOR_REPLY_BASE_US + slot * ANCHOR_SLOT_SPACING_US);
        uint64_t t_tx2 = (t_rx1 + delay_dtu) & TS_MASK_40;

        // uint64_t t_tx2 = (t_rx1 + REPLY_DELAY_DTU) & 0xFFFFFFFFFFULL;

        /* 记录会话（按 Tag 短地址），期望的 FINAL 序号= poll.seq+2 */
        uint16_t tag_id = v.hdr->src;
        ds_sess_t *sess = sess_get_or_alloc(tag_id);
        if (sess) {
            sess->t_rx1 = t_rx1;
            sess->t_tx2 = t_tx2;
            sess->expect_seq = (uint8_t) (v.hdr->seq + 2);
            sess->tick = now_ms;
        }

        /* 组 RESP 并延迟发送，随后自动进 RX 等 FINAL */
        uint8_t txbuf[64];
        uint16_t mac_len = uwb_build_resp(txbuf,
                                          (uint8_t) (v.hdr->seq + 1), /* RESP 的序号 */
                                          v.hdr->pan,
                                          tag_id, /* dest = tag   */
                                          g_anchor_short, /* src  = anchor*/
                                          t_rx1, t_tx2);

        if (dwt_writetxdata(mac_len, txbuf, 0) == DWT_SUCCESS) {
            dwt_writetxfctrl(mac_len + 2, 0, 1); /* +2 含FCS，rng=1 */
            dwt_setrxaftertxdelay(0);
            dwt_setrxtimeout(FINAL_WINDOW_US); /* FINAL 监听窗 */
            dwt_setdelayedtrxtime((uint32_t) (t_tx2 >> 8)); /* 写高32位 */

            /* 新增：告诉 on_tx_done 这次 TX 是给哪个 tag 的 RESP */
            s_sending_resp = 1;
            s_resp_tag_pending = tag_id;

            if (dwt_starttx(DWT_START_TX_DELAYED | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
                g_last_tx_ms = now_ms;
            } else {
                (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            }
        } else {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        } {
            char rx1_hex[11], plan_hex[11];
            ts40_to_hex(rx1_hex, t_rx1);
            ts40_to_hex(plan_hex, t_tx2);

            uart1_printf("[POLL] tag=%u seq=%u rx1=0x%s plan_tx2=0x%s d_us=%ld",
                         (unsigned) tag_id, (unsigned) v.hdr->seq, rx1_hex, plan_hex,
                         (long) rel_us(t_tx2, t_rx1));
        }

        return;
    }

    /* ---------- 处理 FINAL ---------- */
    if (uwb_get_msg_type(&v) == UWB_MSG_FINAL) {
        uint16_t tag_id = v.hdr->src;
        ds_sess_t *sess = sess_find(tag_id);
        if (!sess || !sess->active) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }

        /* （可选）校验序号：只在匹配时计算 */
        if (v.hdr->seq != sess->expect_seq) {
            /* 允许放宽：如果时序宽松也可接受不匹配的 FINAL */
            // (void)dwt_rxenable(DWT_START_RX_IMMEDIATE); return;
        }

        if (v.payload_len < sizeof(pl_final_t)) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }
        const pl_final_t *pf = (const pl_final_t *) v.payload;

        /* Tag 负载中的时间戳（40bit） */
        uint64_t t_tx1 = uwb_ts40_to_64(pf->t_tx1);
        uint64_t t_rx2 = uwb_ts40_to_64(pf->t_rx2);
        uint64_t t_tx3 = uwb_ts40_to_64(pf->t_tx3);

/* 我方收到 POLL 的时刻 T_rx1 */
uint8_t rxts5[5];
dwt_readrxtimestamp(rxts5);
uint64_t t_rx1 = uwb_ts40_to_64(rxts5);

/* ====== 固定时隙：基准 + 槽号×间隔 ====== */
uint8_t slot = anchor_slot_index();
uint32_t off_us = ANCHOR_SLOT_BASE_US + (uint32_t)slot * ANCHOR_SLOT_SPACING_US;
uint64_t t_tx2 = (t_rx1 + US_TO_DTU(off_us)) & TS_MASK_40;

        /* DS-TWR：对称公式（40bit 回卷） */
        // uint64_t Tround1 = (t_rx2 - t_tx1) & TS_MASK_40; /* Tag 视角：POLL→RESP */
        // uint64_t Treply1 = (t_tx2 - t_rx1) & TS_MASK_40; /* Anchor 视角：POLL→RESP */
        // uint64_t Tround2 = (t_rx3 - t_tx2) & TS_MASK_40; /* Anchor 视角：RESP→FINAL */
        // uint64_t Treply2 = (t_tx3 - t_rx2) & TS_MASK_40; /* Tag 视角：RESP→FINAL */

        // /* 常用近似：ToF = ((Tround1 - Treply1) + (Tround2 - Treply2))/4 */
        // double tof_dtu = 0.25 * ((double) ((int64_t) Tround1 - (int64_t) Treply1)
        //                          + (double) ((int64_t) Tround2 - (int64_t) Treply2));
        // if (tof_dtu < 0) tof_dtu = 0;
        // double dist_m = tof_dtu * DWT_TIME_UNITS * SPEED_OF_LIGHT;

        /* 上报/打印 */
        // char out[128];
        // snprintf(out, sizeof(out), "{\"role\":\"anchor\",\"tag\":%u,\"acr\":%u,\"dist\":%.2f}",
        //          (unsigned) tag_id, (unsigned) g_anchor_short, dist_m);
        // uart1_println(out);
        // print_anchor_json_uintmm(tag_id, g_anchor_short, (float) dist_m);

        /* 会话结束 */
        sess_clear(tag_id);
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

        // ---- 差值与 ToF（DTU）----
        // int64_t d1 = (int64_t) ((Tround1 - Treply1) & TS_MASK_40);
        // int64_t d2 = (int64_t) ((Tround2 - Treply2) & TS_MASK_40);
        // int64_t tof_dtu_i64 = (d1 + d2) / 4;
        // if (tof_dtu_i64 < 0) tof_dtu_i64 = 0;

        // // 32 位展示值（足够）
        // int32_t d1_ns = DTU_TO_NS_I32(d1);
        // int32_t d2_ns = DTU_TO_NS_I32(d2);
        // int32_t tof_ns = DTU_TO_NS_I32(tof_dtu_i64);
        // int32_t dist_mm = DTU_TO_MM_I32(tof_dtu_i64);
        //
        // uart1_printf("[FINAL] tag=%u d1=%ldDTU(%ldns) d2=%ldDTU(%ldns) "
        //              "ToF=%ldDTU(%ldns) dist=%ld.%03ldm",
        //              (unsigned) tag_id,
        //              (long) d1, (long) d1_ns,
        //              (long) d2, (long) d2_ns,
                     // (long) tof_dtu_i64, (long) tof_ns,
                     // (long) (dist_mm / 1000), (long) labs(dist_mm % 1000));

        {
            char rx1_hex[11], plan_hex[11];
            ts40_to_hex(rx1_hex, t_rx1);
            ts40_to_hex(plan_hex, t_tx2);
            uart1_printf("[POLL] tag=%u seq=%u slot=%u off_us=%lu rx1=0x%s plan_tx2=0x%s",
                         (unsigned)tag_id, (unsigned)v.hdr->seq,
                         (unsigned)slot, (unsigned long)off_us,
                         rx1_hex, plan_hex);
        }

        return;
    }

    /* 其它帧型忽略 */
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void uart1_printf(const char *fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    HAL_UART_Transmit(&huart1, (uint8_t *) buf, (uint16_t) n, 100);
    const char crlf[2] = {'\r', '\n'};
    HAL_UART_Transmit(&huart1, (uint8_t *) crlf, 2, 100);
}

/* ========== 速率/初始化/主循环 ========== */
void anchor_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms = (uint32_t) (1000.0f / rate + 0.5f);
    // g_min_interval_ms = (uint32_t) (0);
}

void anchor_init(void) {
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_anchor_short);

    char buf[16];
    snprintf(buf, sizeof(buf), "ACR:%04X", (unsigned) g_anchor_short);
    OLED_ShowString(0, 8, buf);

    dwt_setcallbacks(on_tx_done, on_rx_ok, on_rx_to, on_rx_err, NULL, NULL);
    /* ★ 打开 RX 超时中断，否则 FINAL 监听窗到期不会回调 on_rx_to */
    dwt_setinterrupt(
        DWT_INT_RFCG | DWT_INT_TFRS | DWT_INT_RFTO |
        DWT_INT_RFCE | DWT_INT_RPHE | DWT_INT_RFSL |
        DWT_INT_RXOVRR | DWT_INT_CPERR | DWT_INT_ARFE,
        0, DWT_ENABLE_INT);

    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    memset(s_sess, 0, sizeof(s_sess));
    g_last_tx_ms = HAL_GetTick();

    while (dwt_checkirq()) {
        dwt_isr(); // 把“上电遗留”的事件清掉，IRQ 线会回到低电平
    }
}

void anchor_process(void) {
    // 兜底：如果 EXTI 没触发，也能靠轮询把 ISR 拉起来
    // if (dwt_checkirq()) {
    //     dwt_isr();
    // }
}
