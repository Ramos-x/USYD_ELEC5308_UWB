/****************  uwb_tag_anchor.c  (merged)  ****************
 * - Merge of tag.c + anchor.c
 * - Role select via PB2(BOOT1): 0=Anchor, 1=Tag
 * - UART ring buffer shared
 * - Distinct callbacks: tag_on_* / anchor_on_*
 * - Distinct globals for rates, session etc. to avoid conflicts
 *************************************************************/
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdlib.h>

#include "stm32f1xx_hal.h"
#include "main.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "bu03.h"

#include "app.h"
// #include "anchor.h"
// #include "tag.h"
#include "uwb_frames.h"
#include "OLED/oled.h"

/* ================ UART1 环形缓冲 + DMA ================ */
extern UART_HandleTypeDef huart1;

#define UART1_TX_BUF_SZ  2048
static uint8_t uart1_tx_buf[UART1_TX_BUF_SZ];
static volatile uint16_t tx_head = 0; // 写指针
static volatile uint16_t tx_tail = 0; // 读指针
static volatile uint16_t dma_chunk_len = 0; // 本次DMA长度
static volatile uint8_t dma_busy = 0; // 1=DMA正忙

static inline uint16_t uart1_tx_used(void) {
    uint16_t h = tx_head, t = tx_tail;
    return (h >= t) ? (h - t) : (uint16_t) (UART1_TX_BUF_SZ - (t - h));
}

static inline uint16_t uart1_tx_free(void) {
    return (uint16_t) (UART1_TX_BUF_SZ - 1 - uart1_tx_used());
}

static void uart1_kick_dma_if_idle(void) {
    if (dma_busy) return;
    uint16_t used = uart1_tx_used();
    if (!used) return;

    uint16_t contiguous = (tx_head >= tx_tail)
                              ? (tx_head - tx_tail)
                              : (uint16_t) (UART1_TX_BUF_SZ - tx_tail);

    dma_chunk_len = contiguous;
    dma_busy = 1;

    if (HAL_UART_Transmit_DMA(&huart1, &uart1_tx_buf[tx_tail], dma_chunk_len) != HAL_OK) {
        dma_busy = 0;
        dma_chunk_len = 0;
    }
}

static void uart1_write_bytes(const uint8_t *data, uint16_t len) {
    while (len) {
        __disable_irq();
        uint16_t free = uart1_tx_free();
        __enable_irq();
        if (free == 0) {
            HAL_Delay(0);
            continue;
        }
        uint16_t chunk = (len < free) ? len : free;

        uint16_t first = (uint16_t) (UART1_TX_BUF_SZ - tx_head);
        if (first > chunk) first = chunk;
        memcpy(&uart1_tx_buf[tx_head], data, first);
        tx_head = (uint16_t) ((tx_head + first) % UART1_TX_BUF_SZ);

        uint16_t remain = (uint16_t) (chunk - first);
        if (remain) {
            memcpy(&uart1_tx_buf[tx_head], data + first, remain);
            tx_head = (uint16_t) ((tx_head + remain) % UART1_TX_BUF_SZ);
        }
        data += chunk;
        len -= chunk;

        __disable_irq();
        uart1_kick_dma_if_idle();
        __enable_irq();
    }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart != &huart1) return;
    tx_tail = (uint16_t) ((tx_tail + dma_chunk_len) % UART1_TX_BUF_SZ);
    dma_chunk_len = 0;
    if (uart1_tx_used() > 0) {
        dma_busy = 0;
        uart1_kick_dma_if_idle();
    } else {
        dma_busy = 0;
    }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart) {
    if (huart == &huart1) {
        dma_busy = 0;
        dma_chunk_len = 0;
        uart1_kick_dma_if_idle();
    }
}

static void uart1_printf(const char *fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf) - 2, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (n > (int) (sizeof(buf) - 2)) n = (int) (sizeof(buf) - 2);
    uart1_write_bytes((const uint8_t *) buf, (uint16_t) n);
    static const uint8_t crlf[2] = {'\r', '\n'};
    uart1_write_bytes(crlf, 2);
}

/* ================ 公共时基/换算宏 ================ */
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
#define DTU_TO_MM_I32(dtu64) ( (int32_t)((double)(dtu64)*DWT_TIME_UNITS*SPEED_OF_LIGHT*1000.0 + 0.5) )
#endif
#ifndef DTU_TO_NS_I32
#define DTU_TO_NS_I32(dtu64) ( (int32_t)((double)(dtu64)*DWT_TIME_UNITS*1e9 + 0.5) )
#endif

static inline int after40(uint64_t a, uint64_t b) {
    return (((a - b) & TS_MASK_40) < (1ULL << 39));
}

static inline uint64_t max40(uint64_t a, uint64_t b) {
    return after40(a, b) ? a : b;
}

/* 小工具 */
static const char HEXTAB[] = "0123456789ABCDEF";

static void ts40_to_hex(char out[11], uint64_t ts) {
    for (int i = 0; i < 5; i++) {
        uint8_t b = (ts >> (8 * (4 - i))) & 0xFF; // 高位在前
        out[i * 2] = HEXTAB[b >> 4];
        out[i * 2 + 1] = HEXTAB[b & 0xF];
    }
    out[10] = '\0';
}

static inline int32_t rel_us(uint64_t newer, uint64_t older) {
    uint64_t d = (newer - older) & TS_MASK_40;
    return DTU_TO_US_I32(d);
}

/* ================ 公共网络参数 ================ */
static uint16_t g_pan_id = 0xABCD;
static const uint16_t g_bcast = 0xFFFF;

/* ======================= TAG 部分 ======================= */
/* Tag 发送 FINAL 的固定延迟（相对收到 RESP） */
#define TAG_FINAL_DELAY_US   1000U
#define FINAL_CHAIN_GAP_US    1000U
#ifndef RESP_WINDOW_US
#define RESP_WINDOW_US       6000U  //当前 800+4*1000
#endif
#define ACK_WINDOW_US   6000U      /* FINAL 后等待 FACK 的窗口 */
#define FINAL_DELAY_DTU  ((uint64_t)((TAG_FINAL_DELAY_US*1e-6)/DWT_TIME_UNITS + 0.5))
#define FINAL_CHAIN_GAP_DTU US_TO_DTU(FINAL_CHAIN_GAP_US)

/* Tag 侧短地址与状态 */
static uint16_t g_tag_short = 0x1234;
static uint16_t s_wait_ack_anchor = 0; /* 当前 FINAL 期待哪个 Anchor 的ACK */
uint16_t tag_get_short(void) { return g_tag_short; }
void tag_randomize_short(void) { g_tag_short = 0x000A; }

/* Tag 侧日志（保留，可选关闭） */
typedef enum {
    LE_POLL_TX = 0,
    LE_RESP_RX,
    LE_FINAL_SCHED,
    LE_FINAL_TX,
    LE_RESP_WIN_END,
    LE_FINAL_SCHED_FAIL
} log_type_t;

typedef struct {
    uint8_t type, seq, qcnt;
    uint16_t acr;
    uint32_t gap_us;
    uint64_t t1, t2;
} log_evt_t;

#define LOG_CAP 32
static volatile uint8_t s_log_head = 0, s_log_tail = 0;
static log_evt_t s_log_q[LOG_CAP];

static inline int log_push(const log_evt_t *e) {
    __disable_irq();
    uint8_t nt = (uint8_t) ((s_log_tail + 1) % LOG_CAP);
    if (nt == s_log_head) {
        __enable_irq();
        return 0;
    }
    s_log_q[s_log_tail] = *e;
    s_log_tail = nt;
    __enable_irq();
    return 1;
}

static inline int log_pop(log_evt_t *out) {
    __disable_irq();
    if (s_log_head == s_log_tail) {
        __enable_irq();
        return 0;
    }
    *out = s_log_q[s_log_head];
    s_log_head = (uint8_t) ((s_log_head + 1) % LOG_CAP);
    __enable_irq();
    return 1;
}

static void log_flush(void) {
    log_evt_t e;
    char h1[11], h2[11];
    while (log_pop(&e)) {
        switch (e.type) {
            case LE_POLL_TX:
                ts40_to_hex(h1, e.t1);
                uart1_printf("[POLL-TX] seq=%u tx1=0x%s", (unsigned) e.seq, h1);
                break;
            case LE_RESP_RX:
                ts40_to_hex(h1, e.t1);
                uart1_printf("[RESP-RX] acr=%u seq=%u rx2=0x%s qcnt=%u",
                             (unsigned) e.acr, (unsigned) e.seq, h1, (unsigned) e.qcnt);
                break;
            case LE_FINAL_SCHED:
                ts40_to_hex(h1, e.t1);
                ts40_to_hex(h2, e.t2);
                uart1_printf("[FINAL-SCHED] acr=%u rx2=0x%s t_tx3=0x%s gap_us=%lu",
                             (unsigned) e.acr, h1, h2, (unsigned long) e.gap_us);
                break;
            case LE_FINAL_TX:
                ts40_to_hex(h1, e.t1);
                uart1_printf("[FINAL-TX] tx3=0x%s", h1);
                break;
            case LE_RESP_WIN_END:
                uart1_printf("[RESP-WIN-END] qcnt=%u", (unsigned) e.qcnt);
                break;
            case LE_FINAL_SCHED_FAIL:
                ts40_to_hex(h1, e.t1);
                ts40_to_hex(h2, e.t2);
                uart1_printf("[FINAL-SCHED-FAIL] acr=%u rx2=0x%s t_tx3=0x%s gap_us=%lu",
                             (unsigned) e.acr, h1, h2, (unsigned long) e.gap_us);
                break;
            default: break;
        }
    }
}

/* Tag 侧：Anchor 信息聚合（仅日志/上报用） */
typedef struct {
    uint16_t id;
    uint8_t ts[5]; /* 兼容老字段：最近 RX2（保留不删） */
    float dist_m;
    uint32_t last_tick;
    uint8_t updated; /* 有新数据待上报 */

    /* ★ 新增：一次交互的关键时间戳 */
    uint8_t have_xchg; /* 1=本轮交互已完整（至少拿到 FACK） */
    uint8_t seq_final; /* FINAL 的 seq（= RESP.seq+1） */

    uint64_t tx1; /* Tag 发送 POLL(TX1) */
    uint64_t rx2; /* Tag 接收 RESP(RX2) */
    uint64_t tx3_plan; /* Tag 计划 FINAL(TX3 plan) */
    uint64_t tx3_real; /* Tag 实际 FINAL(TX3 real) */
    uint64_t rx3_ack; /* Anchor 在 FACK 中回传的 RX3（Anchor 收到 FINAL 的时刻） */
} anchor_info_t;


#define MAX_ANCHORS 16
static anchor_info_t g_anchors[MAX_ANCHORS];

static inline char hex4(uint8_t v) {
    v &= 0x0F;
    return (char) ((v < 10) ? ('0' + v) : ('A' + (v - 10)));
}

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

/* Tag 侧 FINAL 待发队列 */
typedef struct {
    uint16_t pan, anchor_id;
    uint8_t seq;
    uint64_t t_tx1, t_rx2;
} final_job_t;

#define FINALQ_CAP 8
static final_job_t s_finalq[FINALQ_CAP];
static uint8_t s_qhead = 0, s_qtail = 0, s_qcount = 0;
static uint8_t s_resp_window_over = 0;
static uint64_t s_last_planned_ttx3 = 0;

static inline void finalq_reset(void) { s_qhead = s_qtail = s_qcount = 0; }

static int finalq_push_if_absent(uint16_t pan, uint16_t anchor_id, uint8_t seq, uint64_t t_tx1, uint64_t t_rx2) {
    for (uint8_t i = 0, idx = s_qhead; i < s_qcount; ++i, idx = (uint8_t) ((idx + 1) % FINALQ_CAP))
        if (s_finalq[idx].anchor_id == anchor_id) return 0;
    if (s_qcount >= FINALQ_CAP) return -1;
    s_finalq[s_qtail] = (final_job_t){.pan = pan, .anchor_id = anchor_id, .seq = seq, .t_tx1 = t_tx1, .t_rx2 = t_rx2};
    s_qtail = (uint8_t) ((s_qtail + 1) % FINALQ_CAP);
    s_qcount++;
    return 1;
}

static inline final_job_t *finalq_peek(void) { return s_qcount ? &s_finalq[s_qhead] : NULL; }

static inline void finalq_pop(void) {
    if (!s_qcount) return;
    s_qhead = (uint8_t) ((s_qhead + 1) % FINALQ_CAP);
    s_qcount--;
}

/* Tag 会话与状态 */
typedef enum { TAG_IDLE = 0, TAG_WAIT_RESP, TAG_FINAL_SCHEDULED } tag_phase_t;

static volatile tag_phase_t s_phase = TAG_IDLE;
static volatile uint8_t s_tx_busy = 0;
static volatile uint64_t g_last_poll_tx_ts = 0;

/* Tag 输出速率节流（JSON 上报） */
static volatile uint32_t g_min_interval_ms_tag = 2000;
static volatile uint32_t g_last_tx_ms_tag = 0;
static volatile uint32_t g_last_flush_ms_tag = 0;

/* Tag 主动轮询 */
static uint8_t s_tag_proactive_enabled = 1;
static uint32_t s_tag_poll_interval_ms = 500; // 你可以改回 1000ms
static uint32_t s_tag_last_poll_ms = 0;
static uint8_t s_tag_seq = 0;

/* ===== 顺序轮询地址 0x0001~0x0005 ===== */
#define AID_FIRST 0x0001
#define AID_LAST  0x0005
static const uint16_t s_poll_targets[] = {0x0001, 0x0002, 0x0003, 0x0004, 0x0005};
static const uint8_t s_target_count = sizeof(s_poll_targets) / sizeof(s_poll_targets[0]);
static uint8_t s_target_idx = 0; /* 当前要轮询的目标在上面数组里的索引 */
static uint16_t s_current_anchor = 0; /* 当前这轮交互的 Anchor 短地址（发 POLL 时确定） */

/* 推进到下一个 Anchor（循环 1→5→1） */
static inline void advance_to_next_anchor(void) {
    s_target_idx = (uint8_t) ((s_target_idx + 1) % s_target_count);
    s_current_anchor = 0;
    s_wait_ack_anchor = 0;
    s_phase = TAG_IDLE;
    s_tx_busy = 0;
    s_resp_window_over = 0;
    finalq_reset();
    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* = Tag 内部函数 = */
static void schedule_next_final(void); // 前置声明

static void tag_proactive_try_send_poll(void) {
    if (s_tx_busy) return;

    /* 选择当前要打的 Anchor */
    const uint16_t dest = s_poll_targets[s_target_idx];
    s_current_anchor = dest;

    dwt_forcetrxoff();
    uint8_t tx[32];
    /* !!! 把原来的 g_bcast 改为 dest !!! */
    uint16_t mac_len = uwb_build_poll(tx, s_tag_seq++, g_pan_id, dest, g_tag_short);

    if (dwt_writetxdata(mac_len, tx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(mac_len + 2, 0, 1);
        dwt_setrxaftertxdelay(0);
        dwt_setrxtimeout(RESP_WINDOW_US);
        if (dwt_starttx(DWT_START_TX_IMMEDIATE | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
            s_tx_busy = 1;
            s_phase = TAG_WAIT_RESP;
            s_resp_window_over = 0;
            s_last_planned_ttx3 = 0;
            finalq_reset();
        }
    }
}


static void tag_on_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;
    uint8_t txts5[5];
    dwt_readtxtimestamp(txts5);
    if (s_phase == TAG_WAIT_RESP) {
        g_last_poll_tx_ts = uwb_ts40_to_64(txts5);
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }
    if (s_phase == TAG_FINAL_SCHEDULED) {
        uint64_t tx3_real = uwb_ts40_to_64(txts5);

        /* ★ 记录实际 TX3（用当前等待 FACK 的 anchor id） */
        if (s_wait_ack_anchor) {
            anchor_info_t *ai = find_or_alloc_anchor(s_wait_ack_anchor);
            if (ai) {
                ai->tx3_real = tx3_real;
                ai->updated = 1;
            }
        }

        (void) tx3_real; // 可日志
        finalq_pop();
        if (s_qcount > 0) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            schedule_next_final();
            return;
        }
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
    // fallback
    s_tx_busy = 0;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void tag_on_rx_ok(const dwt_cb_data_t *cb) {
    /* 先把 RX 数据读出来，再解析，然后再分支处理 */
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

    uint8_t type = uwb_get_msg_type(&v);

    /* === FACK === */
    if (type == UWB_MSG_FACK) {
        if (v.payload_len >= sizeof(pl_fack_t)) {
            const pl_fack_t *ack = (const pl_fack_t *)v.payload;

            if (s_phase == TAG_FINAL_SCHEDULED &&
                s_wait_ack_anchor != 0 &&
                v.hdr->src == s_wait_ack_anchor &&
                v.hdr->dst == g_tag_short)
            {
                uint64_t t_rx3 = uwb_ts40_to_64(ack->t_rx3);
                char rx3_hex[11]; ts40_to_hex(rx3_hex, t_rx3);
                uart1_printf("[ACK] acr=%u rx3=0x%s", (unsigned)v.hdr->src, rx3_hex);

                anchor_info_t *ai2 = find_or_alloc_anchor(v.hdr->src);
                if (ai2) {
                    ai2->rx3_ack   = t_rx3;
                    ai2->have_xchg = 1;
                    ai2->updated   = 1;
                }

                s_wait_ack_anchor = 0;
                /* 完成本 Anchor，推进 */
                advance_to_next_anchor();
                return;
            }
        }
        /* 非期望帧：务必重置等待窗口！ */
        if (s_phase == TAG_FINAL_SCHEDULED) {
            dwt_setrxtimeout(ACK_WINDOW_US);                // 重新编程超时
        }
        (void)dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }



    /* === RESP === */
    if (type != UWB_MSG_RESP) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }
    if (v.payload_len < sizeof(pl_resp_t)) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    uint16_t anchor_id = v.hdr->src;
    /* 只处理当前目标 Anchor 的 RESP，其它忽略 */
    if (s_current_anchor == 0 || anchor_id != s_current_anchor) {
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    /* 本端接收该 RESP 的时刻 */
    uint8_t rxts5[5];
    dwt_readrxtimestamp(rxts5);
    uint64_t t_rx2 = uwb_ts40_to_64(rxts5);

    /* 入队 FINAL（去重）: FINAL 序号 = RESP.seq + 1 */
    (void) finalq_push_if_absent(v.hdr->pan, anchor_id, (uint8_t) (v.hdr->seq + 1),
                                 g_last_poll_tx_ts, t_rx2);

    /* ★ 记录本轮交互（以 Anchor 为单位） */
    anchor_info_t *ai = find_or_alloc_anchor(anchor_id);
    if (ai) {
        ai->id = anchor_id;
        /* 原有：保存 ts[5] 为 rx2 的 5B 形式，用于兼容老 JSON */
        uint8_t ts5[5] = {
            (uint8_t) (t_rx2 & 0xFF), (uint8_t) ((t_rx2 >> 8) & 0xFF),
            (uint8_t) ((t_rx2 >> 16) & 0xFF), (uint8_t) ((t_rx2 >> 24) & 0xFF),
            (uint8_t) ((t_rx2 >> 32) & 0xFF)
        };
        memcpy(ai->ts, ts5, 5);

        ai->last_tick = HAL_GetTick();
        ai->dist_m = 0;

        /* ★ 新增：交互时间戳 */
        ai->seq_final = (uint8_t) (v.hdr->seq + 1);
        ai->tx1 = g_last_poll_tx_ts;
        ai->rx2 = t_rx2;
        ai->tx3_plan = 0;
        ai->tx3_real = 0;
        ai->rx3_ack = 0;
        ai->have_xchg = 0; /* 还没拿到 FACK */
        ai->updated = 1; /* 本条会被 JSON 带出去 */
    }


    /* 从 0→1 时立刻排第一帧 FINAL */
    if (s_phase == TAG_WAIT_RESP && s_qcount == 1) {
        schedule_next_final();
        return;
    }

    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void tag_on_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;

    // FACK 超时
    if (s_phase == TAG_FINAL_SCHEDULED) {
        /* 等 FACK 超时：视为本 Anchor 结束，推进到下一个 */
        s_wait_ack_anchor = 0;
        advance_to_next_anchor();
        return;
    }


    // RESP 窗口超时
    s_resp_window_over = 1;
    if (s_phase == TAG_WAIT_RESP) {
        /* 未收到 RESP：也推进到下一个 Anchor */
        advance_to_next_anchor();
        return;
    }


    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void tag_on_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* Tag：FINAL 排程 */
static void schedule_next_final(void) {
    final_job_t *job = finalq_peek();
    if (!job) return;
    uint64_t base_ttx3 = (job->t_rx2 + FINAL_DELAY_DTU) & TS_MASK_40;
    uint64_t t_tx3 = base_ttx3;
    if (s_last_planned_ttx3) {
        uint64_t min_next = (s_last_planned_ttx3 + FINAL_CHAIN_GAP_DTU) & TS_MASK_40;
        t_tx3 = max40(t_tx3, min_next);
    }

    /* ★ 记录计划的 TX3 */
    anchor_info_t *ai = find_or_alloc_anchor(job->anchor_id);
    if (ai) {
        ai->tx3_plan = t_tx3;
        ai->updated = 1;
    }

    uint8_t ftx[64];
    uint16_t flen = uwb_build_final(ftx, job->seq, job->pan,
                                    job->anchor_id, g_tag_short,
                                    job->t_tx1, job->t_rx2, t_tx3);
    if (dwt_writetxdata(flen, ftx, 0) == DWT_SUCCESS) {
        dwt_writetxfctrl(flen + 2, 0, 1);
        dwt_setdelayedtrxtime((uint32_t) (t_tx3 >> 8));
        s_wait_ack_anchor = job->anchor_id;
        dwt_setrxaftertxdelay(0);
        dwt_setrxtimeout(ACK_WINDOW_US);
        if (dwt_starttx(DWT_START_TX_DELAYED | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
            s_last_planned_ttx3 = t_tx3;
            s_phase = TAG_FINAL_SCHEDULED;
            return;
        }
    }
    /* 推迟一格再试 */
    // t_tx3 = (t_tx3 + FINAL_CHAIN_GAP_DTU) & TS_MASK_40;
    // flen = uwb_build_final(ftx, job->seq, job->pan,
    //                        job->anchor_id, g_tag_short,
    //                        job->t_tx1, job->t_rx2, t_tx3);
    // if (dwt_writetxdata(flen, ftx, 0) == DWT_SUCCESS) {
    //     dwt_writetxfctrl(flen + 2, 0, 1);
    //     dwt_setdelayedtrxtime((uint32_t) (t_tx3 >> 8));
    //     s_wait_ack_anchor = job->anchor_id;
    //     dwt_setrxaftertxdelay(0);
    //     dwt_setrxtimeout(ACK_WINDOW_US);
    //     if (dwt_starttx(DWT_START_TX_DELAYED | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
    //         s_last_planned_ttx3 = t_tx3;
    //         s_phase = TAG_FINAL_SCHEDULED;
    //         return;
    //     }
    // }
    /* 彻底失败：丢弃该 job */
    finalq_pop();
}

/* Tag：周期任务 & 输出 */
void uwb_periodic_task(void) {
    if (!s_tag_proactive_enabled) return;
    uint32_t now = HAL_GetTick();
    if ((now - s_tag_last_poll_ms) >= s_tag_poll_interval_ms) {
        s_tag_last_poll_ms = now;
        tag_proactive_try_send_poll();
    }
}

static void try_flush_json(void) {
    uint32_t now = HAL_GetTick();
    if ((now - g_last_flush_ms_tag) < g_min_interval_ms_tag) return;

    int total = 0;
    for (int i = 0; i < MAX_ANCHORS; ++i) if (g_anchors[i].id) total++;
    if (total == 0) {
        g_last_flush_ms_tag = now;
        return;
    }

    char out[1536];
    size_t pos = 0;
    int n = snprintf(out + pos, sizeof(out) - pos,
                     "{\"role\":\"tag\",\"tag\":\"0x%04X\",\"tick\":%lu,\"anchor_count\":%d,\"anchors\":[",
                     (unsigned) g_tag_short, (unsigned long) now, total);
    if (n <= 0) { return; }
    pos += (size_t) n;

    int first = 1;
    for (int i = 0; i < MAX_ANCHORS; ++i) {
        if (!g_anchors[i].id) continue;

        /* 旧字段：ts_hex（沿用为 rx2 的 5B 表达） */
        char ts_hex[11];
        for (int k = 0; k < 5; ++k) {
            ts_hex[k * 2] = hex4(g_anchors[i].ts[k] >> 4);
            ts_hex[k * 2 + 1] = hex4(g_anchors[i].ts[k]);
        }
        ts_hex[10] = '\0';

        long dist_mm = (long) (g_anchors[i].dist_m * 1000.0f + 0.5f);

        /* ★ 新增：把 64b 时间戳转为 5B 十六进制字符串（高位在前） */
        char h_tx1[11] = "0000000000";
        char h_rx2[11] = "0000000000";
        char h_tx3p[11] = "0000000000";
        char h_tx3r[11] = "0000000000";
        char h_rx3[11] = "0000000000";
        if (g_anchors[i].tx1) ts40_to_hex(h_tx1, g_anchors[i].tx1);
        if (g_anchors[i].rx2) ts40_to_hex(h_rx2, g_anchors[i].rx2);
        if (g_anchors[i].tx3_plan) ts40_to_hex(h_tx3p, g_anchors[i].tx3_plan);
        if (g_anchors[i].tx3_real) ts40_to_hex(h_tx3r, g_anchors[i].tx3_real);
        if (g_anchors[i].rx3_ack) ts40_to_hex(h_rx3, g_anchors[i].rx3_ack);

        /* ★ 新增：相对时延(us) */
        int32_t dt_tx1_rx2 = (g_anchors[i].tx1 && g_anchors[i].rx2) ? rel_us(g_anchors[i].rx2, g_anchors[i].tx1) : 0;
        int32_t dt_rx2_tx3p = (g_anchors[i].rx2 && g_anchors[i].tx3_plan)
                                  ? rel_us(g_anchors[i].tx3_plan, g_anchors[i].rx2)
                                  : 0;
        int32_t dt_rx2_tx3r = (g_anchors[i].rx2 && g_anchors[i].tx3_real)
                                  ? rel_us(g_anchors[i].tx3_real, g_anchors[i].rx2)
                                  : 0;
        int32_t dt_tx3r_rx3 = (g_anchors[i].tx3_real && g_anchors[i].rx3_ack)
                                  ? rel_us(g_anchors[i].rx3_ack, g_anchors[i].tx3_real)
                                  : 0;

        /* ★ 输出 JSON：在每个 anchor 下新增 ex{} 与 dt_us{} */
        n = snprintf(out + pos, sizeof(out) - pos,
                     "%s{\"aid\":%u,\"aid_hex\":\"%04X\",\"tick\":%lu,"
                     "\"dist_mm\":%ld,"
                     "\"ts\":\"%s\","  /* 兼容旧字段：仍表示 rx2 的 5B */
                     "\"ex\":{\"seq\":%u,"
                     "\"tx1\":\"%s\",\"rx2\":\"%s\",\"tx3p\":\"%s\",\"tx3r\":\"%s\",\"rx3\":\"%s\","
                     "\"complete\":%u},"
                     "\"dt_us\":{\"tx1_rx2\":%ld,\"rx2_tx3p\":%ld,\"rx2_tx3r\":%ld}"
                     "}",
                     first ? "" : ",",
                     (unsigned) g_anchors[i].id, (unsigned) g_anchors[i].id,
                     (unsigned long) g_anchors[i].last_tick,
                     dist_mm,
                     ts_hex,
                     (unsigned) g_anchors[i].seq_final,
                     h_tx1, h_rx2, h_tx3p, h_tx3r, h_rx3,
                     (unsigned) g_anchors[i].have_xchg,
                     (long) dt_tx1_rx2, (long) dt_rx2_tx3p, (long) dt_rx2_tx3r);


        if (n <= 0) break;
        if ((size_t) n >= (sizeof(out) - pos - 2)) break;
        pos += (size_t) n;
        first = 0;
    }

    if (pos < sizeof(out)) out[pos++] = ']';
    if (pos < sizeof(out)) out[pos++] = '}';
    out[(pos < sizeof(out)) ? pos : (sizeof(out) - 1)] = '\0';

    uart1_write_bytes((const uint8_t *) out, (uint16_t) strlen(out));
    static const uint8_t crlf[2] = {'\r', '\n'};
    uart1_write_bytes(crlf, 2);

    /* 通知应用层：只上报本次有更新的 anchor */
    uint32_t ids[16];
    float dists[16];
    uint32_t cnt = 0;
    for (int i = 0; i < MAX_ANCHORS && cnt < 16; ++i) {
        if (!g_anchors[i].id || !g_anchors[i].updated) continue;
        ids[cnt] = g_anchors[i].id;
        dists[cnt] = g_anchors[i].dist_m;
        g_anchors[i].updated = 0;
        cnt++;
    }
    if (cnt > 0) app_on_tag_ranges(cnt, ids, dists);
    g_last_flush_ms_tag = now;
}

void tag_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms_tag = (uint32_t) (1000.0f / rate + 0.5f);
}

void tag_init(void) {
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_tag_short);

    char buf[16];
    snprintf(buf, sizeof(buf), "TAG:%04X", (unsigned) g_tag_short);
    OLED_ShowString(64, 8, buf);
    OLED_Update();

    dwt_setcallbacks(tag_on_tx_done, tag_on_rx_ok, tag_on_rx_to, tag_on_rx_err, NULL, NULL);
    dwt_setinterrupt(
        DWT_INT_RFCG | DWT_INT_TFRS | DWT_INT_RFTO |
        DWT_INT_RFCE | DWT_INT_RPHE | DWT_INT_RFSL |
        DWT_INT_RXOVRR | DWT_INT_CPERR | DWT_INT_ARFE,
        0, DWT_ENABLE_INT);

    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    memset(g_anchors, 0, sizeof(g_anchors));
    g_last_tx_ms_tag = g_last_flush_ms_tag = HAL_GetTick();

    s_phase = TAG_IDLE;
    s_tx_busy = 0;

    // 预填若干 anchor（可选）
    for (uint16_t aid = 0x0001; aid <= 0x0005; ++aid) {
        anchor_info_t *ai = find_or_alloc_anchor(aid);
        if (ai) {
            ai->last_tick = 0;
            ai->dist_m = 0;
            ai->updated = 0;
            memset(ai->ts, 0, 5);
        }
    }
    while (dwt_checkirq()) dwt_isr();
}

void tag_process(void) {
    uwb_periodic_task();
    log_flush();
    try_flush_json();
    dwt_isr();
}

/* ======================= ANCHOR 部分 ======================= */
/* 固定时隙：槽索引与延迟 */
#define ANCHOR_ID_FIRST         0x0001
#define ANCHOR_ID_LAST          0x0005
#define ANCHOR_SLOT_COUNT      (ANCHOR_ID_LAST - ANCHOR_ID_FIRST + 1) /* =5 */
#define ANCHOR_REPLY_BASE_US    1000U   // 槽0基准
#define ANCHOR_SLOT_SPACING_US  1000U   // 槽间隔
#define FINAL_WINDOW_US         4000U   // 等 FINAL 的窗口，覆盖 TAG_FINAL_DELAY_US

/* Anchor 侧短地址与速率节流 */
static uint16_t g_addr_short = 0x0001;
uint16_t anchor_get_short(void) { return g_addr_short; }
void anchor_randomize_short(void) { g_addr_short = 0x0001; } // 可改为UID映射

static volatile uint32_t g_min_interval_ms_acr = 1; // RESP 节流（可调）
static volatile uint32_t g_last_tx_ms_acr = 0;

/* Anchor 会话记录（每 Tag） */
typedef struct {
    uint16_t tag;
    uint8_t expect_seq; /* 期望 FINAL 序号 = poll.seq + 2 */
    uint64_t t_rx1; /* 我方收到 POLL 的时刻 */
    uint64_t t_tx2; /* 我方计划/实际 RESP 的时刻 */
    uint32_t tick; /* 计时用于过期 */
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
    return NULL;
}

static void sess_clear(uint16_t tag) {
    for (int i = 0; i < SESS_CAP; ++i)
        if (s_sess[i].active && s_sess[i].tag == tag) {
            s_sess[i].active = 0;
            break;
        }
}

static inline uint8_t anchor_slot_index_from_id(uint16_t aid) {
    int32_t delta = (int32_t) aid - (int32_t) ANCHOR_ID_FIRST;
    int32_t span = (int32_t) ANCHOR_SLOT_COUNT;
    int32_t m = delta % span;
    if (m < 0) m += span;
    return (uint8_t) m;
}

static inline uint8_t anchor_slot_index(void) {
    return anchor_slot_index_from_id(g_addr_short);
}

static inline uint64_t plan_tx2_from_rx1(uint64_t t_rx1) {
    uint8_t slot = anchor_slot_index();
    uint32_t off_us = ANCHOR_REPLY_BASE_US + (uint32_t) slot * ANCHOR_SLOT_SPACING_US;
    return (t_rx1 + US_TO_DTU(off_us)) & TS_MASK_40;
}

#define ACR_ACK_DELAY_US 1500U
/* Anchor 侧中断/回调状态 */
static volatile uint8_t s_sending_resp = 0;
static volatile uint16_t s_resp_tag_pending = 0;

/* Anchor 回调 */
static void gc_sessions(void) {
    uint32_t now = HAL_GetTick();
    for (int i = 0; i < SESS_CAP; ++i) {
        if (s_sess[i].active && (now - s_sess[i].tick) > 100) {
            s_sess[i].active = 0;
        }
    }
}

static void anchor_on_tx_done(const dwt_cb_data_t *cb) {
    (void) cb;
    if (s_sending_resp) {
        uint8_t txts5[5];
        dwt_readtxtimestamp(txts5);
        uint64_t real_tx2 = uwb_ts40_to_64(txts5);
        ds_sess_t *sess = sess_find(s_resp_tag_pending);
        if (sess && sess->active) {
            int32_t plan_off_us = rel_us(sess->t_tx2, sess->t_rx1);
            int32_t real_off_us = rel_us(real_tx2, sess->t_rx1);
            char real_hex[11];
            ts40_to_hex(real_hex, real_tx2);
            uart1_printf("[RESP] tag=%u real_tx2=0x%s plan_off=%ldus real_off=%ldus",
                         (unsigned) s_resp_tag_pending, real_hex, (long) plan_off_us, (long) real_off_us);
            sess->t_tx2 = real_tx2;
        }
        s_sending_resp = 0;
    }

    // ★ 不管发的是什么（包括 FACK），TX 完成后都回到 RX
    dwt_rxenable(DWT_START_RX_IMMEDIATE);
}


static void anchor_on_rx_to(const dwt_cb_data_t *cb) {
    (void) cb;
    gc_sessions();
    dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void anchor_on_rx_err(const dwt_cb_data_t *cb) {
    (void) cb;
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

static void anchor_on_rx_ok(const dwt_cb_data_t *cb) {
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

    /* --- POLL --- */
    if (uwb_get_msg_type(&v) == UWB_MSG_POLL) {
        /* 只响应发给我的 unicast 或广播 */
        if (!(v.hdr->dst == g_addr_short || v.hdr->dst == g_bcast)) {
            (void)dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }

        uint32_t now_ms = HAL_GetTick();
        if ((now_ms - g_last_tx_ms_acr) < g_min_interval_ms_acr) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }
        uint8_t rxts5[5];
        dwt_readrxtimestamp(rxts5);
        uint64_t t_rx1 = uwb_ts40_to_64(rxts5);
        uint64_t t_tx2 = plan_tx2_from_rx1(t_rx1);

        uint16_t tag_id = v.hdr->src;
        ds_sess_t *sess = sess_get_or_alloc(tag_id);
        if (sess) {
            sess->t_rx1 = t_rx1;
            sess->t_tx2 = t_tx2;
            sess->expect_seq = (uint8_t) (v.hdr->seq + 2);
            sess->tick = now_ms;
        }

        uint8_t txbuf[64];
        uint16_t mac_len = uwb_build_resp(txbuf,
                                          (uint8_t) (v.hdr->seq + 1),
                                          v.hdr->pan, tag_id, g_addr_short,
                                          t_rx1, t_tx2);
        if (dwt_writetxdata(mac_len, txbuf, 0) == DWT_SUCCESS) {
            dwt_writetxfctrl(mac_len + 2, 0, 1);
            dwt_setrxaftertxdelay(0);
            dwt_setrxtimeout(FINAL_WINDOW_US);
            dwt_setdelayedtrxtime((uint32_t) (t_tx2 >> 8));

            s_sending_resp = 1;
            s_resp_tag_pending = tag_id;
            if (dwt_starttx(DWT_START_TX_DELAYED | DWT_RESPONSE_EXPECTED) == DWT_SUCCESS) {
                g_last_tx_ms_acr = now_ms;
            } else {
                (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            }
        } else {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        } {
            // log
            char rx1_hex[11], plan_hex[11];
            ts40_to_hex(rx1_hex, t_rx1);
            ts40_to_hex(plan_hex, t_tx2);
            uart1_printf("[POLL] tag=%u seq=%u rx1=0x%s plan_tx2=0x%s d_us=%ld",
                         (unsigned) tag_id, (unsigned) v.hdr->seq, rx1_hex, plan_hex,
                         (long) rel_us(t_tx2, t_rx1));
        }
        return;
    }

    /* --- FINAL --- */
    if (uwb_get_msg_type(&v) == UWB_MSG_FINAL) {
        /* 只处理发给我的 FINAL（Tag->Anchor 的 dest 应该是我） */
        if (v.hdr->dst != g_addr_short) {
            (void)dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }
        uint16_t tag_id = v.hdr->src;
        ds_sess_t *sess = sess_find(tag_id);
        if (!sess || !sess->active) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }

        if (v.hdr->seq != sess->expect_seq) {
            /* 放宽处理：不直接 return，可继续解析 */
        }
        if (v.payload_len < sizeof(pl_final_t)) {
            (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
            return;
        }
        const pl_final_t *pf = (const pl_final_t *) v.payload;
        uint64_t t_tx1 = uwb_ts40_to_64(pf->t_tx1);
        uint64_t t_rx2 = uwb_ts40_to_64(pf->t_rx2);
        uint64_t t_tx3 = uwb_ts40_to_64(pf->t_tx3);

        char tx1_hex[11], rx2_hex[11], tx3_hex[11];
        ts40_to_hex(tx1_hex, t_tx1);
        ts40_to_hex(rx2_hex, t_rx2);
        ts40_to_hex(tx3_hex, t_tx3);
        uart1_printf("[FINAL] tag=%u seq=%u tx1=0x%s rx2=0x%s tx3=0x%s",
                     (unsigned) tag_id, (unsigned) v.hdr->seq, tx1_hex, rx2_hex, tx3_hex);

        /* 计划 vs 实际 RESP 延迟核对：一定基于 sess->t_rx1 */
        int32_t plan_us = rel_us(plan_tx2_from_rx1(sess->t_rx1), sess->t_rx1);
        int32_t real_us = rel_us(sess->t_tx2, sess->t_rx1);
        uart1_printf("[RESP-CHECK] tag=%u plan_off=%ldus real_off=%ldus",
                     (unsigned) tag_id, (long) plan_us, (long) real_us);

        /* 记录 Anchor 收到 FINAL 的时刻（RX 时间戳） */
        uint8_t rxts5_final[5];
        dwt_readrxtimestamp(rxts5_final);
        uint64_t t_rx3 = uwb_ts40_to_64(rxts5_final);

        /* 计划一个稍后的 TX4 发 FACK，给RX->TX切换留点裕量 */
        uint64_t t_tx4 = (t_rx3 + US_TO_DTU(ACR_ACK_DELAY_US)) & TS_MASK_40;

        /* 组并发 FACK：seq 用 FINAL.seq + 1 */
        uint8_t ack[48];
        uint16_t ack_len = uwb_build_fack(ack,
                                          (uint8_t) (v.hdr->seq + 1),
                                          v.hdr->pan,
                                          /* dest= */ tag_id,
                                          /* src = */ g_addr_short,
                                          /* t_rx3 */ t_rx3);
        // 发送 FACK 之前：
        dwt_setrxaftertxdelay(0);
        dwt_setrxtimeout(0); // 0 表示无限等待

        // 组并发 FACK 之前
        uart1_printf("[FACK-SCHED] tag=%u t_tx4=+%ldus", (unsigned) tag_id, (long) ACR_ACK_DELAY_US);

        // 延迟发送（会在 TX 后自动回 RX）
        if (dwt_writetxdata(ack_len, ack, 0) == DWT_SUCCESS) {
            dwt_writetxfctrl(ack_len + 2, 0, 1);
            dwt_setdelayedtrxtime((uint32_t) (t_tx4 >> 8));
            int st = dwt_starttx(DWT_START_TX_DELAYED);
            uart1_printf("[FACK-TX] start=%d len=%u", st, ack_len);
            if (st != DWT_SUCCESS) {
                dwt_forcetrxoff();
                dwt_writetxdata(ack_len, ack, 0);
                dwt_writetxfctrl(ack_len + 2, 0, 1);
                st = dwt_starttx(DWT_START_TX_IMMEDIATE);
                uart1_printf("[FACK-TX-IMM] start=%d", st);
            }
        }


        sess_clear(tag_id);
        (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
        return;
    }

    /* 其他帧忽略 */
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);
}

/* Anchor API */
void anchor_set_rate_hz(float rate) {
    if (rate < 0.1f) rate = 0.1f;
    if (rate > 100.0f) rate = 100.0f;
    g_min_interval_ms_acr = (uint32_t) (1000.0f / rate + 0.5f);
}

void anchor_init(void) {
    dwt_setpanid(g_pan_id);
    dwt_setaddress16(g_addr_short);

    char buf[16];
    snprintf(buf, sizeof(buf), "ACR:%04X", (unsigned) g_addr_short);
    OLED_ShowString(0, 8, buf);
    OLED_Update();

    dwt_setcallbacks(anchor_on_tx_done, anchor_on_rx_ok, anchor_on_rx_to, anchor_on_rx_err, NULL, NULL);
    dwt_setinterrupt(
        DWT_INT_RFCG | DWT_INT_TFRS | DWT_INT_RFTO |
        DWT_INT_RFCE | DWT_INT_RPHE | DWT_INT_RFSL |
        DWT_INT_RXOVRR | DWT_INT_CPERR | DWT_INT_ARFE,
        0, DWT_ENABLE_INT);
    dwt_setrxtimeout(0);
    (void) dwt_rxenable(DWT_START_RX_IMMEDIATE);

    memset(s_sess, 0, sizeof(s_sess));
    g_last_tx_ms_acr = HAL_GetTick();

    while (dwt_checkirq()) dwt_isr();
}

void anchor_process(void) {
    gc_sessions();
    dwt_isr();
}

/* ======================= 角色封装（与示例一致） ======================= */
/* 默认定位频率（Hz） */
#ifndef BU03_RATE_HZ_DEFAULT
#define BU03_RATE_HZ_DEFAULT 10.0f
#endif
static float s_rate_hz = BU03_RATE_HZ_DEFAULT;
static int s_init_ok = 0;
static int s_last_err = 0;
/* 运行时角色：由 PB2(BOOT1) 决定，0=Anchor, 1=Tag（上拉为1即Tag） */
static int s_role;

void bu03_reset(void) {
    s_init_ok = 0;
    s_last_err = 0;
    s_rate_hz = BU03_RATE_HZ_DEFAULT;
}

int bu03_init(void) {
    if (s_init_ok) return 0;
    bu03_reset();

    GPIO_PinState pin = HAL_GPIO_ReadPin(BOOT1_GPIO_Port, BOOT1_Pin);
    s_role = (pin == GPIO_PIN_RESET) ? BU03_ROLE_ANCHOR : BU03_ROLE_TAG;

    int rc = UWB_DW3000_Init();
    if (rc != 0) {
        s_last_err = rc;
        return rc;
    }

    if (s_role == BU03_ROLE_ANCHOR) {
        // anchor_randomize_short();
        anchor_init();
    } else {
        // tag_randomize_short();
        tag_init();
    }

    bu03_set_rate_hz(BU03_RATE_HZ_DEFAULT);
    s_init_ok = 1;
    s_last_err = 0;
    return 0;
}

void bu03_process(void) {
    if (s_role == BU03_ROLE_ANCHOR) anchor_process();
    else tag_process();
}

void bu03_set_rate_hz(float rate) {
    s_rate_hz = rate;
    if (s_role == BU03_ROLE_ANCHOR) {
        anchor_set_rate_hz(10); // 控制 RESP 发送节流
    } else {
        tag_set_rate_hz(1); // 控制 JSON 上报频率
    }
}

int bu03_is_ready(void) { return s_init_ok; }
int bu03_get_last_error(void) { return s_last_err; }
float bu03_get_rate_hz(void) { return s_rate_hz; }
int bu03_get_role(void) { return s_role; }
