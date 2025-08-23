#include <string.h>
#include <math.h>
#include "UWB/calibration.h"

#ifndef UWB_CALIB_MAX_ANCHORS
#define UWB_CALIB_MAX_ANCHORS 8U
#endif

#ifndef UWB_CALIB_REQ_INTERVAL_MS
#define UWB_CALIB_REQ_INTERVAL_MS 50U
#endif

#ifndef UWB_CALIB_REQ_TIMEOUT_MS
#define UWB_CALIB_REQ_TIMEOUT_MS 1000U
#endif

static uint32_t s_anchor_ids[UWB_CALIB_MAX_ANCHORS];
static uint32_t s_anchor_count = 0;

static float s_dist[UWB_CALIB_MAX_ANCHORS][UWB_CALIB_MAX_ANCHORS]; /* -1 表示未知 */
static uwb_vec3_t s_pos[UWB_CALIB_MAX_ANCHORS];

static uwb_request_range_cb_t s_request_cb = 0;
static uwb_positions_ready_cb_t s_result_cb = 0;

static uint8_t s_calibrating = 0;
static uint8_t s_waiting_measure = 0;
static uint32_t s_next_pair_i = 0, s_next_pair_j = 1;
static uint32_t s_last_req_ms = 0;
static uint32_t s_last_done_ms = 0;
static uint32_t s_period_ms = 0;

static int index_of_id(uint32_t id) {
    for (uint32_t i = 0; i < s_anchor_count; ++i) {
        if (s_anchor_ids[i] == id) return (int)i;
    }
    return -1;
}

static void reset_distances(void) {
    for (uint32_t i = 0; i < s_anchor_count; ++i) {
        for (uint32_t j = 0; j < s_anchor_count; ++j) {
            s_dist[i][j] = (i == j) ? 0.0f : -1.0f;
        }
    }
}

static int find_next_unmeasured_pair(uint32_t* oi, uint32_t* oj) {
    for (uint32_t i = 0; i < s_anchor_count; ++i) {
        for (uint32_t j = i + 1; j < s_anchor_count; ++j) {
            if (s_dist[i][j] < 0.0f) {
                *oi = i; *oj = j;
                return 1;
            }
        }
    }
    return 0;
}

/* 安全 sqrt */
static inline float safe_sqrtf(float v) {
    return (v > 0.0f) ? sqrtf(v) : 0.0f;
}

/* 依据测得的两两距离，求解三维相对坐标
   约束：A0 位于原点，A1 在 +X 轴，A2 位于 XY 平面（z=0），A3 的 z>0 确定朝向 */
static void compute_positions_3d(void) {
    for (uint32_t i = 0; i < s_anchor_count; ++i) {
        s_pos[i].x = s_pos[i].y = s_pos[i].z = 0.0f;
    }
    if (s_anchor_count == 0) return;

    /* 设 A0 = (0,0,0) */
    s_pos[0].x = s_pos[0].y = s_pos[0].z = 0.0f;

    /* A1 = (d01, 0, 0) */
    if (s_anchor_count >= 2) {
        float d01 = s_dist[0][1];
        if (d01 < 0.0f) d01 = 0.0f;
        s_pos[1].x = d01; s_pos[1].y = 0.0f; s_pos[1].z = 0.0f;
    }

    /* A2 在 XY 平面 */
    if (s_anchor_count >= 3) {
        float d01 = s_dist[0][1];
        float d02 = s_dist[0][2];
        float d12 = s_dist[1][2];
        if (d01 <= 1e-6f || d02 < 0.0f || d12 < 0.0f) {
            s_pos[2].x = s_pos[2].y = s_pos[2].z = 0.0f;
        } else {
            float x2 = (d02*d02 + d01*d01 - d12*d12) / (2.0f * d01);
            float y2 = safe_sqrtf(d02*d02 - x2*x2);
            s_pos[2].x = x2; s_pos[2].y = y2; s_pos[2].z = 0.0f;
        }
    }

    /* A3 及之后：使用 0/1/2 线性差分求 x,y，然后由 d0k 给出 |z|，A3 取 z>0，其他根据与 A3 的距离选符号 */
    if (s_anchor_count >= 4) {
        for (uint32_t k = 3; k < s_anchor_count; ++k) {
            float d0k = s_dist[0][k];
            float d1k = s_dist[1][k];
            float d2k = s_dist[2][k];
            float x1 = s_pos[1].x;
            float x2 = s_pos[2].x, y2 = s_pos[2].y;

            if (d0k < 0.0f || d1k < 0.0f || d2k < 0.0f || x1 <= 1e-6f || fabsf(y2) <= 1e-6f) {
                s_pos[k].x = s_pos[k].y = s_pos[k].z = 0.0f;
                continue;
            }

            /* 从 (A1 - A0) 得 x */
            float xk = (x1*x1 + d0k*d0k - d1k*d1k) / (2.0f * x1);

            /* 从 (A2 - A0) 得 y（线性） */
            float rhs2 = d2k*d2k - d0k*d0k - (x2*x2 + y2*y2);
            /* -2*x2*xk - 2*y2*yk = rhs2  => yk = ( -rhs2 - 2*x2*xk ) / (2*y2) */
            float yk = ( -rhs2 - 2.0f*x2*xk ) / (2.0f * y2);

            /* 由球面 (A0) 得 |z| */
            float zk_abs = safe_sqrtf(d0k*d0k - xk*xk - yk*yk);

            float zk = zk_abs;
            if (k == 3) {
                /* 定义坐标系朝向：A3 取 z>0 */
                zk = zk_abs;
            } else {
                /* 与 A3 的距离选择符号（若可用） */
                float d3k = s_dist[3][k];
                if (d3k > 0.0f) {
                    float dx = xk - s_pos[3].x;
                    float dy = yk - s_pos[3].y;
                    float r_plus  = fabsf(safe_sqrtf(dx*dx + dy*dy + ( zk_abs - s_pos[3].z)*( zk_abs - s_pos[3].z)) - d3k);
                    float r_minus = fabsf(safe_sqrtf(dx*dx + dy*dy + (-zk_abs - s_pos[3].z)*(-zk_abs - s_pos[3].z)) - d3k);
                    zk = (r_plus <= r_minus) ? zk_abs : -zk_abs;
                } else {
                    zk = zk_abs; /* 回退为正 */
                }
            }

            s_pos[k].x = xk; s_pos[k].y = yk; s_pos[k].z = zk;
        }
    }
}

/* 3x3 线性方程组求解（用于最小二乘正规方程），返回 1 成功 0 失败 */
static int solve3x3(float A11,float A12,float A13,
                    float A21,float A22,float A23,
                    float A31,float A32,float A33,
                    float b1,float b2,float b3,
                    float* x,float* y,float* z) {
    float det = A11*(A22*A33 - A23*A32) - A12*(A21*A33 - A23*A31) + A13*(A21*A32 - A22*A31);
    if (fabsf(det) < 1e-6f) return 0;
    float inv11 =  (A22*A33 - A23*A32) / det;
    float inv12 = -(A12*A33 - A13*A32) / det;
    float inv13 =  (A12*A23 - A13*A22) / det;
    float inv21 = -(A21*A33 - A23*A31) / det;
    float inv22 =  (A11*A33 - A13*A31) / det;
    float inv23 = -(A11*A23 - A13*A21) / det;
    float inv31 =  (A21*A32 - A22*A31) / det;
    float inv32 = -(A11*A32 - A12*A31) / det;
    float inv33 =  (A11*A22 - A12*A21) / det;

    *x = inv11*b1 + inv12*b2 + inv13*b3;
    *y = inv21*b1 + inv22*b2 + inv23*b3;
    *z = inv31*b1 + inv32*b2 + inv33*b3;
    return 1;
}

/* 面向标签的三维定位（最小二乘）：给定锚点坐标与标签到各锚点的距离，解标签坐标 */
int uwb_solve_tag_3d(const uwb_vec3_t* anchors, uint32_t count, const float* d_tag, uwb_vec3_t* tag_out) {
    if (!anchors || !d_tag || !tag_out || count < 4) return 0;
    /* 使用 anchors[0] 作为参考，构造 A x = b 的正规方程 A^T A x = A^T b */
    float AtA11=0,AtA12=0,AtA13=0, AtA22=0,AtA23=0,AtA33=0;
    float Atb1=0, Atb2=0, Atb3=0;
    const uwb_vec3_t p0 = anchors[0];
    float d0 = d_tag[0];

    for (uint32_t i = 1; i < count; ++i) {
        float Ai1 = -2.0f * (anchors[i].x - p0.x);
        float Ai2 = -2.0f * (anchors[i].y - p0.y);
        float Ai3 = -2.0f * (anchors[i].z - p0.z);
        float bi  = (d_tag[i]*d_tag[i] - d0*d0) - ((anchors[i].x*anchors[i].x + anchors[i].y*anchors[i].y + anchors[i].z*anchors[i].z)
                                                  - (p0.x*p0.x + p0.y*p0.y + p0.z*p0.z));

        AtA11 += Ai1*Ai1;
        AtA12 += Ai1*Ai2;
        AtA13 += Ai1*Ai3;
        AtA22 += Ai2*Ai2;
        AtA23 += Ai2*Ai3;
        AtA33 += Ai3*Ai3;

        Atb1  += Ai1*bi;
        Atb2  += Ai2*bi;
        Atb3  += Ai3*bi;
    }

    float x,y,z;
    if (!solve3x3(AtA11,AtA12,AtA13,
                  AtA12,AtA22,AtA23,
                  AtA13,AtA23,AtA33,
                  Atb1, Atb2, Atb3,
                  &x,&y,&z)) {
        return 0;
    }
    tag_out->x = x;
    tag_out->y = y;
    tag_out->z = z;
    return 1;
}

/* 提供外部获取当前锚点三维坐标的接口 */
const uwb_vec3_t* uwb_calib_get_positions(uint32_t* count) {
    if (count) *count = s_anchor_count;
    return s_pos;
}

/* 提供外部获取当前锚点 ID 列表（按内部顺序） */
uint32_t uwb_calib_get_anchor_ids(uint32_t* out_ids, uint32_t max_out) {
    if (!out_ids || max_out == 0) return s_anchor_count;
    uint32_t n = (s_anchor_count < max_out) ? s_anchor_count : max_out;
    memcpy(out_ids, s_anchor_ids, n * sizeof(uint32_t));
    return s_anchor_count;
}

void uwb_calib_init(uint32_t anchor_count,
                    const uint32_t* anchor_ids,
                    uwb_request_range_cb_t request_cb,
                    uwb_positions_ready_cb_t result_cb) {
    s_request_cb = request_cb;
    s_result_cb = result_cb;
    uwb_calib_set_anchors(anchor_count, anchor_ids);
    s_calibrating = 0;
    s_waiting_measure = 0;
    s_last_req_ms = 0;
    s_last_done_ms = 0;
    s_period_ms = 0;
}

void uwb_calib_set_anchors(uint32_t anchor_count, const uint32_t* anchor_ids) {
    if (anchor_count > UWB_CALIB_MAX_ANCHORS) anchor_count = UWB_CALIB_MAX_ANCHORS;
    s_anchor_count = anchor_count;
    if (anchor_ids && anchor_count) {
        memcpy(s_anchor_ids, anchor_ids, anchor_count * sizeof(uint32_t));
    }
    reset_distances();
}

void uwb_calib_set_period_ms(uint32_t period_ms) {
    s_period_ms = period_ms;
}

void uwb_calib_request(void) {
    if (s_anchor_count < 2) return;
    reset_distances();
    s_calibrating = 1;
    s_waiting_measure = 0;
    s_next_pair_i = 0;
    s_next_pair_j = 1;
}

void uwb_calib_tick(uint32_t now_ms) {
    /* 周期触发 */
    if (!s_calibrating && s_period_ms > 0U) {
        if ((uint32_t)(now_ms - s_last_done_ms) >= s_period_ms) {
            uwb_calib_request();
        }
    }

    if (!s_calibrating || s_anchor_count < 2) return;

    /* 寻找未测对 */
    if (!s_waiting_measure) {
        if (!find_next_unmeasured_pair(&s_next_pair_i, &s_next_pair_j)) {
            /* 全部完成，计算位置并回调（3D） */
            compute_positions_3d();
            if (s_result_cb) {
                s_result_cb(s_pos, s_anchor_count);
            }
            s_calibrating = 0;
            s_last_done_ms = now_ms;
            return;
        }
        if (s_request_cb && (uint32_t)(now_ms - s_last_req_ms) >= UWB_CALIB_REQ_INTERVAL_MS) {
            uint32_t a_id = s_anchor_ids[s_next_pair_i];
            uint32_t b_id = s_anchor_ids[s_next_pair_j];
            s_request_cb(a_id, b_id);
            s_last_req_ms = now_ms;
            s_waiting_measure = 1;
        }
    } else {
        /* 等待测距，超时则重发 */
        if ((uint32_t)(now_ms - s_last_req_ms) >= UWB_CALIB_REQ_TIMEOUT_MS) {
            if (s_request_cb) {
                uint32_t a_id = s_anchor_ids[s_next_pair_i];
                uint32_t b_id = s_anchor_ids[s_next_pair_j];
                s_request_cb(a_id, b_id);
                s_last_req_ms = now_ms;
            }
        }
    }
}

void uwb_calib_on_range(uint32_t a_id, uint32_t b_id, float distance_m) {
    int ia = index_of_id(a_id);
    int ib = index_of_id(b_id);
    if (ia < 0 || ib < 0 || ia == ib) return;
    if (ia > ib) {
        int t = ia; ia = ib; ib = t;
    }
    s_dist[ia][ib] = s_dist[ib][ia] = distance_m;
    /* 若正好是当前等待的一对，则标记可继续下一对 */
    if (s_calibrating && s_waiting_measure) {
        if ((uint32_t)ia == s_next_pair_i && (uint32_t)ib == s_next_pair_j) {
            s_waiting_measure = 0;
        }
    }
}
