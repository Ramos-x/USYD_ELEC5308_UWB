#include "app.h"

#include <stdio.h>

#include "OLED/oled.h"
#include "UWB/calibration.h"
#include "UWB/bu03.h"
#include "UWB/uwb.h"
#include "UWB/tag.h"
#include "UWB/anchor.h"


/* UI 状态管理 */
typedef enum {
    UI_CALIBRATING = 0,
    UI_READY
} ui_state_t;

static ui_state_t s_ui_state = UI_READY;
static uint32_t s_anchor_count = 0;

/* 标签定位缓存（是否已有有效解与最近一次解算坐标） */
static int s_have_tag = 0;
static uwb_vec3_t s_tag_pos;

/* 最近一次测距结果（Tag 角色使用） */
static uint32_t s_last_range_ids[8];
static float s_last_ranges[8];
static uint32_t s_last_range_count = 0;

/* UWB 初始化状态：0=未完成/失败，1=OK */
static int s_uwb_ok = 0;
/* 启动与初始化延后状态 */
static uint32_t s_boot_ms = 0;
static int s_uwb_init_started = 0;
static uint32_t s_next_retry_ms = 0;
static int s_uwb_retry_count = 0;

/* ===== 工具：将整数（带符号，放大10倍）格式化为 "+12.3" 样式 ===== */
static void fmt_signed_dec1(int v10, char out[6]) {
    /* out 长度至少 6（含 '\0'），格式：符号 1 + 整数 2 + '.' + 小数 1 */
    int neg = (v10 < 0);
    int a10 = neg ? -v10 : v10;
    int i = (a10 / 10) % 100; /* 限 2 位整数显示 */
    int d = a10 % 10;
    out[0] = neg ? '-' : '+';
    out[1] = (char) ('0' + (i / 10));
    out[2] = (char) ('0' + (i % 10));
    out[3] = '.';
    out[4] = (char) ('0' + d);
    out[5] = '\0';
}

/* 头栏：显示角色与 UWB 初始化状态 */
static void draw_header(void) {
    if (bu03_get_role() == BU03_ROLE_TAG) {
        OLED_ShowString(0, 0, "ROLE:TAG");
        OLED_ShowString(64, 0, "UWB:OK");
        char idbuf[16];
        (void) snprintf(idbuf, sizeof(idbuf), "TAG:%04X", (unsigned) tag_get_short());
        OLED_ShowString(64, 8, idbuf);
    } else if (bu03_get_role() == BU03_ROLE_ANCHOR) {
        OLED_ShowString(0, 0, "ROLE:ANC");
        OLED_ShowString(64, 0, "UWB:OK");
        char idbuf[16];
        (void) snprintf(idbuf, sizeof(idbuf), "ANC:%04X", (unsigned) anchor_get_short());
        OLED_ShowString(64, 8, idbuf);
    } else {
        OLED_ShowString(0, 0, "ROLE:");
        OLED_ShowString(64, 0, "UWB:");
    }
}

/* ===== UI 绘制：就绪界面（显示锚点数量与标签坐标） ===== */
static void ui_draw_ready(void) {
    OLED_Clear();
    draw_header();
    OLED_ShowString(0, 8, "READY");
    char line[22];
    if (bu03_get_role() == BU03_ROLE_TAG) {
        /* Anchors count (Tag only) */
        line[0] = 'A';
        line[1] = 'C';
        line[2] = 'R';
        line[3] = ':';
        line[4] = ' ';
        uint32_t n = s_anchor_count;
        char buf[10];
        int bi = 0;
        if (n == 0) buf[bi++] = '0';
        else {
            char tmp[10];
            int ti = 0;
            while (n && ti < 10) {
                tmp[ti++] = (char) ('0' + (n % 10));
                n /= 10;
            }
            while (ti) { buf[bi++] = tmp[--ti]; }
        }
        int idx = 5;
        for (int k = 0; k < bi && idx < (int) sizeof(line) - 1; k++) line[idx++] = buf[k];
        line[idx] = '\0';
        OLED_ShowString(0, 16, line);
    }

    if (s_have_tag) {
        char v[6];
        int x10 = (int) (s_tag_pos.x * 10.0f), y10 = (int) (s_tag_pos.y * 10.0f), z10 = (int) (s_tag_pos.z * 10.0f);

        fmt_signed_dec1(x10, v);
        line[0] = 'X';
        line[1] = ':';
        line[2] = ' ';
        line[3] = v[0];
        line[4] = v[1];
        line[5] = v[2];
        line[6] = v[3];
        line[7] = v[4];
        line[8] = '\0';
        OLED_ShowString(0, 24, line);

        fmt_signed_dec1(y10, v);
        line[0] = 'Y';
        line[1] = ':';
        line[2] = ' ';
        line[3] = v[0];
        line[4] = v[1];
        line[5] = v[2];
        line[6] = v[3];
        line[7] = v[4];
        line[8] = '\0';
        OLED_ShowString(0, 32, line);

        fmt_signed_dec1(z10, v);
        line[0] = 'Z';
        line[1] = ':';
        line[2] = ' ';
        line[3] = v[0];
        line[4] = v[1];
        line[5] = v[2];
        line[6] = v[3];
        line[7] = v[4];
        line[8] = '\0';
        OLED_ShowString(0, 40, line);
    } else {
        /* 未获得坐标解：按角色展示等待/测距信息 */
        if (bu03_get_role() == BU03_ROLE_TAG) {
            if (s_last_range_count > 0) {
                /* 显示前 3 个距离，格式近似 "12.3m"（去掉符号） */
                char v[6];
                uint32_t show = (s_last_range_count > 3) ? 3 : s_last_range_count;
                for (uint32_t i = 0; i < show; ++i) {
                    int d10 = (int) (s_last_ranges[i] * 10.0f + 0.5f);
                    fmt_signed_dec1(d10, v);
                    /* 组行：Dn: 12.3m （去掉符号位 v[0]） */
                    int idxl = 0;
                    line[idxl++] = 'D';
                    line[idxl++] = (char) ('0' + (int) i);
                    line[idxl++] = ':';
                    line[idxl++] = ' ';
                    line[idxl++] = v[1];
                    line[idxl++] = v[2];
                    line[idxl++] = v[3];
                    line[idxl++] = v[4];
                    line[idxl++] = 'm';
                    line[idxl] = '\0';
                    OLED_ShowString(0, 24 + (int) i * 8, line);
                }
                /* 如果不足 3 条，余下行不用刷新 */
            } else {
                OLED_ShowString(0, 24, "Waiting Anchors...");
            }
        } else {
            /* ACR 角色 */
            OLED_ShowString(0, 24, "Waiting Tag...");
        }
    }
    OLED_Update();
}


/* ============ 面向底层的标签距离上报接口 ============ */
void app_on_tag_ranges(uint32_t count, const uint32_t *anchor_ids) {
    if (!anchor_ids || count == 0) return;

    /* 缓存最近一次测距（最多 8 个），供 UI 展示 */
    if (count > 8) count = 8;
    s_last_range_count = count;
    for (uint32_t i = 0; i < count; ++i) {
        s_last_range_ids[i] = anchor_ids[i];
        s_last_ranges[i];
    }
    if (s_ui_state == UI_READY && bu03_get_role() == BU03_ROLE_TAG) {
        ui_draw_ready();
    }

    /* 取当前已标定锚点与坐标 */
    uint32_t calib_n = 0;
    const uwb_vec3_t *anchors = uwb_calib_get_positions(&calib_n);
    if (!anchors || calib_n < 4) return;

    /* 获取已标定的锚点 ID 列表，并与上报的距离进行对齐（取交集子集解算） */
    uint32_t calib_ids[8];
    /* 若实现存在最大限制，这里假设不超过 8 */
    if (calib_n > 8) calib_n = 8;

    uwb_vec3_t sel_anchors[8];
    float sel_dist[8];
    uint32_t sel_n = 0;

    for (uint32_t i = 0; i < calib_n && sel_n < 8; ++i) {
        uint32_t id_need = calib_ids[i];
        /* 在线上报中查找该 id */
        for (uint32_t j = 0; j < count; ++j) {
            if (anchor_ids[j] == id_need) {
                sel_anchors[sel_n] = anchors[i];
                // sel_dist[sel_n] = distances_m[j];
                sel_n++;
                break;
            }
        }
    }

    if (sel_n >= 4) {
        uwb_vec3_t tag;
        if (uwb_solve_tag_3d(sel_anchors, sel_n, sel_dist, &tag)) {
            s_tag_pos = tag;
            s_have_tag = 1;
            if (s_ui_state == UI_READY) {
                ui_draw_ready();
            }
        }
    }
}

/* ============ 应用入口实现 ============ */

void app_init(I2C_HandleTypeDef *i2c_for_oled) {
    /* OLED 初始化与欢迎信息 */
    OLED_Init(i2c_for_oled);

    /* 开机信息显示 */
    OLED_Clear();
    OLED_ShowString(16, 0, "UWB Positioning");
    OLED_ShowString(0, 16, "FW v1.0");
    OLED_ShowString(0, 24, __DATE__);
    OLED_ShowString(0, 32, __TIME__);
    OLED_Update();
    HAL_Delay(1000);

    /* 提示 UWB 初始化 */
    // OLED_Clear();
    // OLED_ShowString(0, 0, "UWB 1");
    // OLED_Update();

    s_ui_state = UI_READY;
    s_anchor_count = 0;
    s_have_tag = 0;


    /* 延后 UWB 初始化到 app_process，避免卡死在 bu03_init */
    s_boot_ms = HAL_GetTick();
    s_uwb_init_started = 0;
    s_uwb_retry_count = 0;
    s_next_retry_ms = s_boot_ms + 100U;

    // OLED_Clear();
    // draw_header();
    // OLED_ShowString(0, 8, "Waiting UWB...");
    // OLED_Update();

    /* 延后 UWB 初始化，避免在 app_init 阶段卡死 */
    uint32_t now = HAL_GetTick();
    s_uwb_init_started = 1;

    /* 提示 UWB 初始化 */
    OLED_Clear();
    draw_header();
    OLED_ShowString(0, 8, "UWB 1");
    OLED_Update();

    const int rc = bu03_init(); //                  重置
    if (rc == 0) {
        s_uwb_ok = 1;

        /* 简要显示初始化完成与角色/状态 */
        OLED_Clear();
        draw_header();
        OLED_ShowString(0, 8, "UWB 2");
        OLED_Update();
        // HAL_Delay(200);
        ui_draw_ready();
    } else {
        /* 显示失败并准备重试 */
        OLED_Clear();
        draw_header();
        OLED_ShowString(0, 8, "UWB FAIL");
        OLED_ShowString(0, 16, "Retrying...");
        OLED_Update();

        s_uwb_init_started = 0;
        s_uwb_retry_count++;
        if (s_uwb_retry_count >= 5) {
            OLED_Clear();
            draw_header();
            OLED_ShowString(0, 8, "UWB ERROR");
            OLED_ShowString(0, 16, "Check module");
            OLED_Update();

            /* 停止进一步重试，等待人工干预/复位 */
            s_next_retry_ms = 0xFFFFFFFFu;
            s_uwb_init_started = 1;
        } else {
            s_next_retry_ms = now + 500U;
        }
    }
}

void app_process(void) {
    /* UWB 处理（中断与协议驱动） */
    bu03_process();

    /* LED_RUN */
    static uint32_t s_last_run_ms = 0;
    const uint32_t now = HAL_GetTick();
    if (now - s_last_run_ms >= 1000U) {
        HAL_GPIO_WritePin(LED_RUN_GPIO_Port, LED_RUN_Pin, GPIO_PIN_SET);
        s_last_run_ms = now;
    } else if (now - s_last_run_ms == 40U) {
        HAL_GPIO_WritePin(LED_RUN_GPIO_Port, LED_RUN_Pin, GPIO_PIN_RESET);
    }
}
