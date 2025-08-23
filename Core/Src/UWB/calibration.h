#ifndef UWB_CALIBRATION_H
#define UWB_CALIBRATION_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float x;
    float y;
    float z;
} uwb_vec3_t;

/* 测距请求回调：请求对 (a_id, b_id) 进行一次测距，完成后需调用 uwb_calib_on_range(a_id,b_id,dist_m) */
typedef void (*uwb_request_range_cb_t)(uint32_t a_id, uint32_t b_id);
/* 结果回调：当一次校准完成后，返回各锚点相对坐标（以 anchors[0] 为原点，anchors[1] 在 +X 轴） */
typedef void (*uwb_positions_ready_cb_t)(const uwb_vec3_t* positions, uint32_t count);

/* 初始化：设置初始锚点集合以及回调 */
void uwb_calib_init(uint32_t anchor_count,
                    const uint32_t* anchor_ids,
                    uwb_request_range_cb_t request_cb,
                    uwb_positions_ready_cb_t result_cb);

/* 动态设置锚点集合（覆盖先前设置） */
void uwb_calib_set_anchors(uint32_t anchor_count, const uint32_t* anchor_ids);

/* 设置周期（毫秒）。period_ms=0 关闭周期触发 */
void uwb_calib_set_period_ms(uint32_t period_ms);

/* 手动触发一次全体锚点的相对标定（将逐对测距并计算坐标） */
void uwb_calib_request(void);

/* 周期性调度（建议每次循环调用，now_ms=HAL_GetTick()） */
void uwb_calib_tick(uint32_t now_ms);

/* 由测距结果上报（当底层完成对 (a_id,b_id) 的测距时调用） */
void uwb_calib_on_range(uint32_t a_id, uint32_t b_id, float distance_m);

/* 获取当前锚点三维坐标（内部存储指针只读），count 返回锚点数量 */
const uwb_vec3_t* uwb_calib_get_positions(uint32_t* count);

/* 获取当前锚点 ID 列表（按内部顺序），返回总数；可传入 out_ids（数量不超过 max_out）拷贝出去 */
uint32_t uwb_calib_get_anchor_ids(uint32_t* out_ids, uint32_t max_out);

/* 三维标签定位：给定锚点坐标、标签到各锚点的距离（米），输出标签坐标。返回1成功0失败 */
int uwb_solve_tag_3d(const uwb_vec3_t* anchors, uint32_t count, const float* d_tag, uwb_vec3_t* tag_out);

#ifdef __cplusplus
}
#endif

#endif /* UWB_CALIBRATION_H */
