#include "main.h"
#include <string.h>
#include <stdint.h>
#include "UWB/discovery.h"

/* 复用校准模块的最大锚点上限，若未定义则给出默认值 */
#ifndef UWB_CALIB_MAX_ANCHORS
#define UWB_CALIB_MAX_ANCHORS 8U
#endif

static uint32_t s_ids[UWB_CALIB_MAX_ANCHORS];
static uint32_t s_count = 0;
static uint32_t s_running = 0;
static uint32_t s_max_keep = UWB_CALIB_MAX_ANCHORS;
static uint32_t s_end_ms = 0;

static uwb_discovery_done_cb_t s_done_cb = 0;

static int contains_id(uint32_t id) {
    for (uint32_t i = 0; i < s_count; ++i) {
        if (s_ids[i] == id) return 1;
    }
    return 0;
}

void uwb_discovery_set_done_cb(uwb_discovery_done_cb_t cb) {
    s_done_cb = cb;
}

void uwb_discovery_start(uint32_t duration_ms, uint32_t max_anchors) {
    if (max_anchors == 0 || max_anchors > UWB_CALIB_MAX_ANCHORS) {
        s_max_keep = UWB_CALIB_MAX_ANCHORS;
    } else {
        s_max_keep = max_anchors;
    }
    s_count = 0;
    s_running = 1;
    s_end_ms = HAL_GetTick() + duration_ms;
}

void uwb_discovery_tick(uint32_t now_ms) {
    if (!s_running) return;
    if ((int32_t)(now_ms - s_end_ms) < 0) {
        /* 未到期 */
        if (s_count >= s_max_keep) {
            /* 提前结束 */
            s_running = 0;
            if (s_done_cb) s_done_cb(s_ids, s_count);
        }
        return;
    }
    /* 到期 */
    s_running = 0;
    if (s_done_cb) s_done_cb(s_ids, s_count);
}

void uwb_discovery_on_anchor(uint32_t anchor_id) {
    if (!s_running) return;
    if (contains_id(anchor_id)) return;
    if (s_count < s_max_keep) {
        s_ids[s_count++] = anchor_id;
    }
}

int uwb_discovery_is_running(void) {
    return (int)s_running;
}

uint32_t uwb_discovery_get_anchors(uint32_t* out_ids, uint32_t max_out) {
    if (!out_ids || max_out == 0) return s_count;
    uint32_t n = (s_count < max_out) ? s_count : max_out;
    memcpy(out_ids, s_ids, n * sizeof(uint32_t));
    return n;
}
