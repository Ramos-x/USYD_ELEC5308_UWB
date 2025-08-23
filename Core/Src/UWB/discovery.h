#ifndef UWB_DISCOVERY_H
#define UWB_DISCOVERY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 发现完成回调，返回发现到的锚点 ID 列表 */
typedef void (*uwb_discovery_done_cb_t)(const uint32_t* ids, uint32_t count);

/* 启动发现（duration_ms 发现时长，max_anchors 最多保存的锚点数量） */
void uwb_discovery_start(uint32_t duration_ms, uint32_t max_anchors);

/* 周期调度，now_ms=HAL_GetTick() */
void uwb_discovery_tick(uint32_t now_ms);

/* UWB 层上报：发现到一个锚点 ID（重复将自动去重） */
void uwb_discovery_on_anchor(uint32_t anchor_id);

/* 设置发现完成回调 */
void uwb_discovery_set_done_cb(uwb_discovery_done_cb_t cb);

/* 查询是否仍在发现中 */
int uwb_discovery_is_running(void);

/* 获取当前已发现的锚点列表。
 * - 若提供 out_ids 且 max_out>0：返回实际拷贝的数量（不超过 max_out）
 * - 否则：返回当前已发现的总数量
 */
uint32_t uwb_discovery_get_anchors(uint32_t* out_ids, uint32_t max_out);

#ifdef __cplusplus
}
#endif

#endif /* UWB_DISCOVERY_H */
