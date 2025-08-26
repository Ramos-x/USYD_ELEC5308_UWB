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
#include "uwb_frames.h"

/* 距离换算常量（DW 时基） */
#ifndef DWT_TIME_UNITS
#define DWT_TIME_UNITS (1.0/ (499.2e6 * 128.0))
#endif

/* Tag 发送 FINAL 的延迟（相对收到 RESP 的时刻），保证足够的处理裕量 */
//2000 µs 很保守、稳定。后续可按空口负载缩短到几百微秒，但要确保 ≥ DW 芯片要求的最小延迟（几十微秒量级）且预留处理时间。
#define TAG_FINAL_DELAY_US   2000U
#define FINAL_DELAY_DTU ((uint64_t)((TAG_FINAL_DELAY_US * 1e-6) / DWT_TIME_UNITS + 0.5))

#ifndef SPEED_OF_LIGHT
#define SPEED_OF_LIGHT 299702547.0
#endif


/* —— 一轮内多 Anchor 串行 FINAL 的时间规划 —— */
#ifndef US_TO_DTU
#define US_TO_DTU(us) ((uint64_t)(((us) * 1e-6) / DWT_TIME_UNITS + 0.5))
#endif

/* FINAL 与下一个 FINAL 之间至少间隔（含空口+处理裕量），可按速率/负载微调 */
#define FINAL_CHAIN_GAP_US   800U
#define FINAL_CHAIN_GAP_DTU  US_TO_DTU(FINAL_CHAIN_GAP_US)

/* 本轮 RESP 监听窗口（应覆盖 Anchor 的整个时隙窗 + 余量） */
#ifndef RESP_WINDOW_US
#define RESP_WINDOW_US  6000U   /* 示例：6 ms；按你的时隙参数调整 */
#endif

/* —— 待发 FINAL 队列（小环形）—— */
typedef struct {
    uint16_t pan;
    uint16_t anchor_id;
    uint8_t seq; /* 建议用 RESP 的 seq+1 作为 FINAL 的序号 */
    uint64_t t_tx1; /* 本轮 POLL 的 T_tx1 */
    uint64_t t_rx2; /* 我方收到该 Anchor RESP 的时刻 */
} final_job_t;

#define FINALQ_CAP  8
static final_job_t s_finalq[FINALQ_CAP];
static uint8_t s_qhead = 0, s_qtail = 0, s_qcount = 0;
static uint8_t s_resp_window_over = 0; /* 本轮监听窗是否结束 */
static uint64_t s_last_planned_ttx3 = 0; /* 上一个 FINAL 计划的 t_tx3（40bit） */

static inline void finalq_reset(void) {
    s_qhead = s_qtail = s_qcount = 0;
}

static int finalq_push_if_absent(uint16_t pan, uint16_t anchor_id, uint8_t seq,
                                 uint64_t t_tx1, uint64_t t_rx2) {
    /* 去重：同一 Anchor 一轮只发一个 FINAL（需要更多策略可自行扩展） */
    for (uint8_t i = 0, idx = s_qhead; i < s_qcount; ++i, idx = (uint8_t) ((idx + 1) % FINALQ_CAP)) {
        if (s_finalq[idx].anchor_id == anchor_id) return 0; /* 已在队列 */
    }
    if (s_qcount >= FINALQ_CAP) return -1; /* 满 */
    s_finalq[s_qtail] = (final_job_t){.pan = pan, .anchor_id = anchor_id, .seq = seq, .t_tx1 = t_tx1, .t_rx2 = t_rx2};
    s_qtail = (uint8_t) ((s_qtail + 1) % FINALQ_CAP);
    s_qcount++;
    return 1;
}

static inline final_job_t *finalq_peek(void) {
    return (s_qcount ? &s_finalq[s_qhead] : NULL);
}

static inline void finalq_pop(void) {
    if (!s_qcount) return;
    s_qhead = (uint8_t) ((s_qhead + 1) % FINALQ_CAP);
    s_qcount--;
}

/* 40bit上取最大值（t 是 40bit 环形计数）*/
static inline uint64_t max40(uint64_t a, uint64_t b) {
    return ((int64_t) ((a - b) & 0xFFFFFFFFFFULL) >= 0) ? a : b;
}


/* 最近一次 POLL 的 TX 时间戳（40bit，放入 64bit） */
static volatile uint64_t g_last_poll_tx_ts = 0;

/* UART1 由 CubeMX 生成于 main.c */
extern UART_HandleTypeDef huart1;

/* 网络参数：PAN 与短地址（示例值，可按需修改） */
static uint16_t g_pan_id = 0xDECA;
static uint16_t g_tag_short = 0x1234;
static const uint16_t g_broadcast_short = 0xFFFF;

/* 基于芯片唯一ID生成16位短地址，保证不同设备不会重复 */
void tag_randomize_short(void) {
    uint32_t u0 = HAL_GetUIDw0();
    uint32_t u1 = HAL_GetUIDw1();
    uint32_t u2 = HAL_GetUIDw2();

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
    g_tag_short = id;
}

/* 提供对外读取 Tag 短地址的接口 */
uint16_t tag_get_short(void) { return g_tag_short; }

/* 聚合 ANCHOR 信息 */
typedef struct {
    uint16_t id;
    uint8_t ts[5]; /* 40-bit RX timestamp from anchor payload */
    float dist_m; /* 单边 TWR 计算得到的距离（米） */
    uint32_t last_tick;
    uint8_t updated;
} anchor_info_t;

#define MAX_ANCHORS 16
static anchor_info_t g_anchors[MAX_ANCHORS];

static anchor_info_t *find_or_alloc_anchor(uint16_t id) {
    int free_idx = -1;
    for (int i = 0; i < MAX_ANCHORS; ++i) {
        if (g_anchors[i].id == id) return &g_anchors[i];
        if (free_idx < 0 && g_anchors[i].id == 0) free_idx = i;
    }
    if (free_idx >= 0) {
        g_anchors[free_idx].id = id;
        return &g_anchors[free_idx];
    }
    return NULL;
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

/* ========== 用户回调 ========== */
static volatile uint8_t s_tx_busy = 0;

// [SESSION LOCK] 新增：会话阶段
typedef enum { TAG_IDLE = 0, TAG_WAIT_RESP, TAG_FINAL_SCHEDULED } tag_phase_t;

static volatile tag_phase_t s_phase = TAG_IDLE;

/* TX 完成：区分是 POLL 还是 FINAL */
static void on_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;
    uint8_t txts5[5];
    dwt_readtxtimestamp(txts5);

    if (s_phase == TAG_WAIT_RESP) {
        // 刚发完 POLL：记录 T_tx1，继续等 RESP（不解锁）
        g_last_poll_tx_ts = uwb_ts40_to_64(txts5);
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    if (s_phase == TAG_FINAL_SCHEDULED) {
        /* 当前 FINAL 成功发出：弹出队首 */
        finalq_pop();

        if (s_qcount > 0) {
            /* 队列还有 Anchor：继续排程下一帧 FINAL */
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE); // 发前保持接收，直到真正 TX 时间
            schedule_next_final();
            return;
        }

        /* 队列空了：若监听窗已结束 -> 本轮结束；否则回到“等 RESP”继续收 */
        if (s_resp_window_over) {
            s_phase = TAG_IDLE;
            s_tx_busy = 0;
            dwt_setrxtimeout(0);
        } else {
            s_phase = TAG_WAIT_RESP;
        }
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    // 兜底：不应到达
    s_tx_busy = 0;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void on_rx_ok(const dwt_cb_data_t *cb) {
    if (s_phase != TAG_WAIT_RESP && s_phase != TAG_FINAL_SCHEDULED) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

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
    if (uwb_get_msg_type(&v) != UWB_MSG_RESP) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }
    if (v.payload_len < sizeof(pl_resp_t)) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    const pl_resp_t *pl = (const pl_resp_t *) v.payload;
    uint16_t anchor_id = v.hdr->src;

    /* 本端接收该 RESP 的时刻 */
    uint8_t rxts5[5];
    dwt_readrxtimestamp(rxts5);
    uint64_t t_rx2 = uwb_ts40_to_64(rxts5);

    /* 入队（去重）：FINAL 的序号用 (RESP.seq + 1) */
    (void) finalq_push_if_absent(v.hdr->pan, anchor_id, (uint8_t) (v.hdr->seq + 1),
                                 g_last_poll_tx_ts, t_rx2);

    /* 可选：这里仍保留你的 SS-TWR 估距（用于调试/UI），略 */

    /* 如果当前还没有排程 FINAL，则立刻尝试为队首排一个 */

    if (s_phase == TAG_WAIT_RESP && s_qcount == 1) {
        /* 队列从 0→1，立刻排第一帧 FINAL */
        schedule_next_final();
        return;
    }

    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void on_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;
    s_resp_window_over = 1;

    if (s_phase == TAG_WAIT_RESP) {
        if (s_qcount > 0) {
            /* 窗结束但还有待发 FINAL：立即开始串行发 */
            schedule_next_final();
        } else {
            /* 无待发：本轮结束 */
            s_phase = TAG_IDLE;
            s_tx_busy = 0;
            dwt_setrxtimeout(0);
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        }
        return;
    }

    /* 若已在 TAG_FINAL_SCHEDULED，就等 on_tx_done() 收尾 */
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


/* RX 错误：不解锁，继续本轮会话 */
static void on_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* --------- 定时输出 JSON：聚合收到的锚点响应并上报 --------- */
static volatile uint32_t g_min_interval_ms = 500;
static volatile uint32_t g_last_tx_ms = 0;
static volatile uint32_t g_last_flush_ms = 0;

static void try_flush_json(void) {
    uint32_t now = HAL_GetTick();
    if ((now - g_last_flush_ms) < g_min_interval_ms) return;

    int has_any = 0;
    for (int i = 0; i < MAX_ANCHORS; ++i)
        if (g_anchors[i].id && g_anchors[i].updated) {
            has_any = 1;
            break;
        }
    if (!has_any) {
        g_last_flush_ms = now;
        return;
    }

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
        if (!g_anchors[i].id || !g_anchors[i].updated) continue;
        if (!first) { if (pos < sizeof(out)) out[pos++] = ','; }
        first = 0;

        char ts_hex[11];
        for (int k = 0; k < 5; ++k) {
            ts_hex[k * 2] = hex4(g_anchors[i].ts[k] >> 4);
            ts_hex[k * 2 + 1] = hex4(g_anchors[i].ts[k]);
        }
        ts_hex[10] = '\0';

        n = snprintf(out + pos, sizeof(out) - pos,
                     "{\"id\":%u,\"ts\":\"%s\",\"tick\":%lu,\"dist\":%.2f}",
                     (unsigned) g_anchors[i].id, ts_hex,
                     (unsigned long) g_anchors[i].last_tick,
                     (double) g_anchors[i].dist_m);
        if (n < 0) break;
        pos += (size_t) n;

        if (cnt < 16) {
            ids[cnt] = g_anchors[i].id;
            dists[cnt] = g_anchors[i].dist_m;
            cnt++;
        }
        g_anchors[i].updated = 0;
    }
    if (pos < sizeof(out)) out[pos++] = ']';
    if (pos < sizeof(out)) out[pos++] = '}';
    out[(pos < sizeof(out)) ? pos : (sizeof(out) - 1)] = '\0';
    uart1_println(out);

    if (cnt > 0) app_on_tag_ranges(cnt, ids, dists);
    g_last_flush_ms = now;
}

void tag_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms = (uint32_t) (1000.0f / rate + 0.5f);
}

/* ====================== Tag 主动 POLL ====================== */
static uint8_t s_tag_proactive_enabled = 1;
static uint32_t s_tag_poll_interval_ms = 400;
static uint32_t s_tag_last_poll_ms = 0;
static uint8_t s_tag_seq = 0;

/* 发 POLL：进入“等待 RESP”阶段并上锁 */
static void tag_proactive_try_send_poll(void) {
    if (s_tx_busy) return;
    dwt_forcetrxoff();

    uint8_t tx[32];
    uint16_t mac_len = uwb_build_poll(tx, s_tag_seq++, g_pan_id, g_broadcast_short, g_tag_short);

    if (dwt_writetxdata(mac_len, tx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(mac_len + 2, 0, 1);
        dwt_setrxaftertxdelay(0);
        dwt_setrxtimeout(RESP_WINDOW_US); /* 覆盖完整时隙窗的监听时间 */

        if (dwt_starttx(DWT_START_TX_IMMEDIATE | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
            s_tx_busy = 1;
            s_phase = TAG_WAIT_RESP;
            s_resp_window_over = 0;
            s_last_planned_ttx3 = 0;
            finalq_reset();
        }
    }
}

/* 构建并排程下一帧 FINAL（队首），成功则转入 TAG_FINAL_SCHEDULED */
static void schedule_next_final(void) {
    final_job_t *job = finalq_peek();
    if (!job) return;

    const uint64_t TS_MASK_40 = 0xFFFFFFFFFFULL;

    /* 该 Anchor 希望的基准发送时刻：其 RESP 被我们收到后的固定延迟 */
    uint64_t base_ttx3 = (job->t_rx2 + FINAL_DELAY_DTU) & TS_MASK_40;

    /* 串行链：确保与上一帧 FINAL 相隔至少 FINAL_CHAIN_GAP_DTU */
    uint64_t t_tx3 = base_ttx3;
    if (s_last_planned_ttx3) {
        uint64_t min_next = (s_last_planned_ttx3 + FINAL_CHAIN_GAP_DTU) & TS_MASK_40;
        t_tx3 = max40(t_tx3, min_next);
    }

    /* 组 FINAL（带 T_tx1/T_rx2/T_tx3） */
    uint8_t ftx[64];
    uint16_t flen = uwb_build_final(ftx, job->seq, job->pan,
                                    job->anchor_id, g_tag_short,
                                    job->t_tx1, job->t_rx2, t_tx3);

    /* 发起延迟发送 */
    if (dwt_writetxdata(flen, ftx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(flen + 2, 0, 1);
        dwt_setdelayedtrxtime((uint32_t) (t_tx3 >> 8));

        if (dwt_starttx(DWT_START_TX_DELAYED) == DWT_SUCCESS) {
            s_phase = TAG_FINAL_SCHEDULED;
            s_last_planned_ttx3 = t_tx3;
            return;
        }
    }

    /* 如果失败（可能错过时间），小幅推迟一格再试一次；再失败就丢弃该 job */
    t_tx3 = (t_tx3 + FINAL_CHAIN_GAP_DTU) & TS_MASK_40;
    if (dwt_writetxdata(flen, ftx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(flen + 2, 0, 1);
        dwt_setdelayedtrxtime((uint32_t) (t_tx3 >> 8));
        if (dwt_starttx(DWT_START_TX_DELAYED) == DWT_SUCCESS) {
            s_phase = TAG_FINAL_SCHEDULED;
            s_last_planned_ttx3 = t_tx3;
            return;
        }
    }

    /* 彻底失败：丢弃该 Anchor，本轮继续 */
    finalq_pop();
}


/* 对外周期任务：按周期主动发 POLL */
void uwb_periodic_task(void) {
    if (!s_tag_proactive_enabled) return;

    uint32_t now = HAL_GetTick();
    if ((now - s_tag_last_poll_ms) >= s_tag_poll_interval_ms) {
        s_tag_last_poll_ms = now;
        tag_proactive_try_send_poll();
    }
}

void tag_init(void) {
    /* 设置 PAN 与短地址 */
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_tag_short);

    /* OLED 显示 */
    char buf[16];
    snprintf(buf, sizeof(buf), "TAG:%04X", (unsigned) g_tag_short);
    OLED_ShowString(64, 8, buf);
    OLED_Update();

    /* 回调与中断（可按需扩展 RX 错误/超时类中断） */
    dwt_setcallbacks(on_tx_done, on_rx_ok, on_rx_to, on_rx_err, NULL, NULL);
    dwt_setinterrupt(
        DWT_INT_RFCG | DWT_INT_TFRS | DWT_INT_RFTO |
        DWT_INT_RFCE | DWT_INT_RPHE | DWT_INT_RFSL |
        DWT_INT_RXOVRR | DWT_INT_CPERR | DWT_INT_ARFE,
        0, DWT_ENABLE_INT);

    /* 持续接收 */
    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    memset(g_anchors, 0, sizeof(g_anchors));
    g_last_tx_ms = g_last_flush_ms = HAL_GetTick();

    s_phase = TAG_IDLE; // [SESSION LOCK]
    s_tx_busy = 0;

    while (dwt_checkirq()) {
        dwt_isr(); // 把“上电遗留”的事件清掉，IRQ 线会回到低电平
    }
}

void tag_process(void) {
    uwb_periodic_task();
    try_flush_json();
}
