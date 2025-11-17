/**
 * @file uwb_protocol_config.h
 * @brief UWB协议配置参数 - 统一配置文件
 *
 * 此文件定义了UWB DS-TWR协议的所有时序参数。
 * 所有Tag和Anchor实现必须使用相同的参数以确保协议兼容性。
 *
 * @warning 修改这些参数需要确保Tag和Anchor同时更新
 */

#ifndef UWB_PROTOCOL_CONFIG_H
#define UWB_PROTOCOL_CONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

/* ==================== 协议时序参数 ==================== */

/**
 * @brief Tag发送FINAL帧的延迟时间（微秒）
 *
 * Tag在收到RESP后，等待此时间后发送FINAL帧。
 * 此值必须与Anchor的FINAL窗口配置匹配。
 *
 * 注意：bu03.c和tag.c必须使用相同的值
 */
#define TAG_FINAL_DELAY_US      1500U

/**
 * @brief 链式FINAL之间的间隔时间（微秒）
 *
 * 当Tag需要向多个Anchor发送FINAL时，每个FINAL之间的间隔。
 */
#define FINAL_CHAIN_GAP_US      600U

/**
 * @brief Anchor等待FINAL的窗口时间（微秒）
 *
 * Anchor发送RESP后，等待Tag的FINAL帧的最大时间。
 */
#define RESP_WINDOW_US          6000U

/**
 * @brief Tag等待ACK的窗口时间（微秒）
 *
 * Tag发送FINAL后，等待Anchor的ACK帧的最大时间。
 */
#define ACK_WINDOW_US           6000U

/**
 * @brief Anchor发送RESP的延迟时间（微秒）
 *
 * Anchor在收到POLL后，等待此时间后发送RESP帧。
 */
#define ANCHOR_RESP_DELAY_US    1000U

/**
 * @brief 轮询周期（毫秒）
 *
 * Tag发送POLL请求的周期。
 */
#define POLL_PERIOD_MS          100U

/* ==================== 天线延迟校准 ==================== */

/**
 * @brief TX天线延迟初始值（DWT时间单位）
 *
 * 用于补偿TX路径的硬件延迟。
 * 此值通过校准确定，范围通常在16400-16500之间。
 */
#define TX_ANT_DLY_INIT         16436UL

/**
 * @brief RX天线延迟初始值（DWT时间单位）
 *
 * 用于补偿RX路径的硬件延迟。
 */
#define RX_ANT_DLY_INIT         16436UL

/* ==================== 缓冲区大小配置 ==================== */

/**
 * @brief UART TX环形缓冲区大小
 *
 * 必须是2的幂次方（用于快速模运算）。
 */
#define UART1_TX_BUF_SZ         1024U

/**
 * @brief 最大UWB帧长度（字节）
 */
#define MAX_UWB_FRAME_LEN       127U

/**
 * @brief JSON输出缓冲区大小（字节）
 *
 * 用于格式化输出到串口的JSON数据。
 * 警告：较大的缓冲区会占用大量栈空间。
 */
#define JSON_OUTPUT_BUF_SIZE    1024U

/* ==================== 日志配置 ==================== */

/**
 * @brief 日志队列容量
 *
 * 存储待输出的测距事件数量。
 */
#define LOG_QUEUE_CAPACITY      32U

/**
 * @brief 最大Anchor数量
 *
 * Tag可以同时跟踪的最大Anchor数量。
 */
#define MAX_ANCHORS             8U

/* ==================== 超时配置 ==================== */

/**
 * @brief DWT操作超时时间（毫秒）
 *
 * 等待DWT操作完成的最大时间。
 */
#define DWT_TIMEOUT_MS          100U

/**
 * @brief DW1000复位后延迟时间（毫秒）
 *
 * DW1000规格要求：复位后至少等待10ms才能访问。
 */
#define DW_RESET_DELAY_MS       15U

/* ==================== 协议版本 ==================== */

/**
 * @brief 协议主版本号
 */
#define UWB_PROTOCOL_VERSION_MAJOR  1

/**
 * @brief 协议次版本号
 */
#define UWB_PROTOCOL_VERSION_MINOR  0

/**
 * @brief 协议补丁版本号
 */
#define UWB_PROTOCOL_VERSION_PATCH  0

/* ==================== 编译时检查 ==================== */

/* 确保UART缓冲区大小是2的幂 */
#if ((UART1_TX_BUF_SZ & (UART1_TX_BUF_SZ - 1)) != 0)
#error "UART1_TX_BUF_SZ must be a power of 2"
#endif

/* 确保JSON缓冲区不会太大导致栈溢出 */
#if (JSON_OUTPUT_BUF_SIZE > 2048)
#warning "JSON_OUTPUT_BUF_SIZE is very large and may cause stack overflow"
#endif

#ifdef __cplusplus
}
#endif

#endif /* UWB_PROTOCOL_CONFIG_H */
