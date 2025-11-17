# Tag-Anchor通信流程统一文档

## 文档概述

本文档说明了bu03.c中Tag和Anchor之间通信流程的统一优化工作，解决了协议实现中的不一致性问题，确保Tag和Anchor能够可靠地进行DS-TWR测距。

**优化日期**: 2025-01-17
**涉及文件**: Core/Src/UWB/bu03.c, Core/Src/UWB/uwb_protocol_config.h

---

## 1. 发现的问题

### 1.1 严重错误

#### 问题 #1: 编译错误 - 错误的字段名
**位置**: bu03.c:1645
**严重程度**: 🔴 CRITICAL - 导致编译失败

```c
// 错误代码
static const tx_cfg_t s_acr_tx_final = {
    .delay_step = 200,  // ❌ 字段不存在！
    .max_retry = 2
};
```

**原因**: `tx_cfg_t`结构体中没有`delay_step`字段，正确的字段名是`retry_step`。

**影响**: 代码无法编译通过。

---

#### 问题 #2: 时间戳字段混淆
**位置**: bu03.c:640
**严重程度**: 🔴 CRITICAL - 导致距离计算错误

```c
// 错误代码
g_tag_refactored_ctx.tx2_an = uwb_ts40_to_64(pr->t_rx2);  // ❌ 使用了RX时间戳
```

**原因**: 应该使用Anchor的RESP发送时间戳`t_tx2`，而不是接收时间戳`t_rx2`。

**影响**:
- DS-TWR公式中使用错误的时间戳
- 导致距离计算完全错误
- Tag无法获得正确的测距结果

**DS-TWR公式**:
```
tRound1 = t_rx1 - t_tx1  (Tag收到RESP - Tag发送POLL)
tRound2 = t_rx3 - t_tx2  (Tag收到FACK - Anchor发送RESP)  ← 需要t_tx2!
tReply1 = t_tx2 - t_rx1  (Anchor发送RESP - Anchor收到POLL)
tReply2 = t_tx3 - t_rx2  (Tag发送FINAL - Tag收到RESP)

ToF = (tRound1 × tRound2 - tReply1 × tReply2) / (tRound1 + tRound2 + tReply1 + tReply2)
```

---

### 1.2 协议参数不一致

#### 问题 #3: ANCHOR_RESP_DELAY_US 硬编码不一致
**位置**: bu03.c:1385
**严重程度**: 🟡 HIGH - 影响协议兼容性

```c
// 旧代码
#define ANCHOR_REPLY_BASE_US    800U   // ❌ 与配置不一致
```

**问题**:
- 配置文件定义为 `ANCHOR_RESP_DELAY_US = 1000U`
- 实际使用的硬编码值为 `800U`
- Tag和Anchor使用不同的延迟值

**影响**:
- Tag的接收窗口与Anchor的发送时机不匹配
- 可能导致RESP帧丢失
- 降低测距成功率

---

#### 问题 #4: TAG_FINAL_DELAY_US 硬编码不一致
**位置**: bu03.c:1796
**严重程度**: 🟡 HIGH - 影响协议兼容性

```c
// 旧代码
#define ACR_ACK_DELAY_US 1500U  // 虽然值正确，但应使用配置常量
```

**问题**: 硬编码值，不使用统一配置。

---

#### 问题 #5: 重试策略不统一
**严重程度**: 🟡 MEDIUM

**Tag侧重试配置**:
```c
static const tx_cfg_t s_tag_tx_poll = {
    .retry_step = FINAL_CHAIN_GAP_US,  // 600μs
    .max_retry = 2
};
```

**Anchor侧重试配置（修复前）**:
```c
static const tx_cfg_t s_acr_tx_final = {
    .delay_step = 200,  // ❌ 不同的间隔
    .max_retry = 2      // ✓ 相同的次数
};
```

**影响**:
- 重试逻辑不对称
- 调试困难
- 难以分析通信失败原因

---

### 1.3 超时处理不完善

#### 问题 #6: Tag RX超时回调缺少状态区分
**位置**: bu03.c:757-769
**严重程度**: 🟡 MEDIUM

```c
// 旧代码
static void tag_on_rx_to_refactored(const dwt_cb_data_t *cb) {
    if (g_tag_refactored_ctx.state == TAG_ST_WAIT_RESP) {
        tag_advance_anchor();
    } else if (g_tag_refactored_ctx.state == TAG_ST_WAIT_FACK) {
        tag_advance_anchor();
    } else {
        dwt_rxenable(DWT_START_RX_IMMEDIATE);  // ❌ 缺少日志
    }
}
```

**问题**:
- 在`TAG_ST_POLL_TX`和`TAG_ST_FINAL_TX`状态收到RX超时时没有记录日志
- 难以调试异常超时
- 无法区分预期超时和异常超时

---

#### 问题 #7: Anchor垃圾回收超时不精确
**位置**: bu03.c:1469-1491
**严重程度**: 🟡 MEDIUM

```c
// 旧代码
static void anchor_gc_txn(void) {
    uint32_t timeout_ms = 100;  // ❌ 所有状态使用相同超时

    if (g_anchor_txn[i].state == ANCHOR_ST_WAIT_FINAL) {
        timeout_ms = (FINAL_WINDOW_US / 1000) + 50;  // 只有这个状态有特殊处理
    }
}
```

**问题**:
- `ANCHOR_ST_IDLE`: 使用100ms过长，浪费资源
- `ANCHOR_ST_RESP_SCHED`: 使用100ms过长
- `ANCHOR_ST_FACK_SCHED`: 使用100ms过长
- 没有充分利用协议配置中定义的窗口时间

---

## 2. 修复方案

### 2.1 修复编译错误

```c
// 修复后
static const tx_cfg_t s_acr_tx_final = {
    .retry_step = FINAL_CHAIN_GAP_US,  // ✓ 使用正确字段名和统一配置
    .max_retry = 2
};
```

**改进**:
- ✅ 使用正确的字段名`retry_step`
- ✅ 使用统一配置`FINAL_CHAIN_GAP_US`
- ✅ 与Tag侧重试策略保持一致

---

### 2.2 修复时间戳字段混淆

```c
// 修复后
g_tag_refactored_ctx.tx2_an = uwb_ts40_to_64(pr->t_tx2);  // ✓ 使用RESP发送时间戳
```

**验证**:
```c
// RESP帧payload中包含的时间戳
typedef struct {
    uint8_t t_rx1[5];   // Anchor收到POLL的时间
    uint8_t t_tx2[5];   // Anchor发送RESP的时间  ← 这个！
} uwb_payload_resp_t;
```

---

### 2.3 统一协议参数

#### 修复 ANCHOR_REPLY_BASE_US

```c
// 修复前
#define ANCHOR_REPLY_BASE_US    800U

// 修复后
#define ANCHOR_REPLY_BASE_US    ANCHOR_RESP_DELAY_US  // 1000μs (来自配置)
```

#### 修复 ACR_ACK_DELAY_US

```c
// 修复前
#define ACR_ACK_DELAY_US 1500U

// 修复后
#define ACR_ACK_DELAY_US TAG_FINAL_DELAY_US  // 1500μs (来自配置)
```

**优势**:
- ✅ 所有延迟值从`uwb_protocol_config.h`统一管理
- ✅ 修改配置只需改一个文件
- ✅ Tag和Anchor自动保持同步

---

### 2.4 改进超时处理

#### Tag RX超时回调增强

```c
// 修复后
static void tag_on_rx_to_refactored(const dwt_cb_data_t *cb) {
    (void)cb;

    switch (g_tag_refactored_ctx.state) {
        case TAG_ST_WAIT_RESP:
            uart1_printf("[RESP-TO] anchor=%u", g_tag_refactored_ctx.target_anchor);
            tag_advance_anchor();
            break;

        case TAG_ST_WAIT_FACK:
            uart1_printf("[FACK-TO] anchor=%u", g_tag_refactored_ctx.target_anchor);
            tag_advance_anchor();
            break;

        case TAG_ST_IDLE:
        case TAG_ST_POLL_TX:
        case TAG_ST_FINAL_TX:
            // 这些状态下不应该收到RX超时，记录异常
            uart1_printf("[RX-TO-UNEXPECTED] state=%d", g_tag_refactored_ctx.state);
            dwt_rxenable(DWT_START_RX_IMMEDIATE);
            break;

        default:
            uart1_printf("[RX-TO-UNKNOWN] state=%d", g_tag_refactored_ctx.state);
            dwt_rxenable(DWT_START_RX_IMMEDIATE);
            break;
    }
}
```

**改进**:
- ✅ 使用`switch`语句提高可读性
- ✅ 为所有状态添加明确处理
- ✅ 异常超时有明确的日志标记
- ✅ 便于调试和问题定位

---

#### Anchor垃圾回收优化

```c
// 修复后
static void anchor_gc_txn(void) {
    uint32_t now = HAL_GetTick();
    for (int i = 0; i < ANCHOR_MAX_CONCURRENT_TAGS; i++) {
        if (g_anchor_txn[i].active) {
            uint32_t age_ms = now - g_anchor_txn[i].state_entry_ms;
            uint32_t timeout_ms;

            // 根据状态设置精确的超时时间
            switch (g_anchor_txn[i].state) {
                case ANCHOR_ST_IDLE:
                    timeout_ms = 10;  // IDLE状态快速清理
                    break;

                case ANCHOR_ST_RESP_SCHED:
                    timeout_ms = 50;  // 发送RESP的调度窗口
                    break;

                case ANCHOR_ST_WAIT_FINAL:
                    timeout_ms = (RESP_WINDOW_US / 1000) + 100;  // 等待FINAL的超时
                    break;

                case ANCHOR_ST_FACK_SCHED:
                    timeout_ms = 50;  // 发送FACK的调度窗口
                    break;

                default:
                    timeout_ms = 100;  // 未知状态使用默认超时
                    break;
            }

            if (age_ms > timeout_ms) {
                uart1_printf("[GC] tag=%u state=%d age=%lums",
                            g_anchor_txn[i].tag_id,
                            g_anchor_txn[i].state,
                            (unsigned long)age_ms);
                anchor_free_txn(&g_anchor_txn[i]);
            }
        }
    }
}
```

**改进**:
- ✅ 每个状态有精确的超时时间
- ✅ IDLE状态10ms快速清理，释放资源
- ✅ WAIT_FINAL使用协议配置的窗口时间
- ✅ 调度状态使用短超时（50ms）

---

## 3. 统一的协议参数

所有协议参数现在都在`uwb_protocol_config.h`中统一定义：

```c
/* 协议时序参数 */
#define TAG_FINAL_DELAY_US      1500U   // Tag发送FINAL的延迟
#define FINAL_CHAIN_GAP_US      600U    // 链式FINAL之间的间隔
#define RESP_WINDOW_US          6000U   // Anchor等待FINAL的窗口
#define ACK_WINDOW_US           6000U   // Tag等待ACK的窗口
#define ANCHOR_RESP_DELAY_US    1000U   // Anchor发送RESP的延迟
#define POLL_PERIOD_MS          100U    // 轮询周期

/* 天线延迟 */
#define TX_ANT_DLY_INIT         16436UL
#define RX_ANT_DLY_INIT         16436UL

/* 缓冲区大小 */
#define UART1_TX_BUF_SZ         1024U
#define MAX_UWB_FRAME_LEN       127U
#define JSON_OUTPUT_BUF_SIZE    1024U

/* 超时配置 */
#define DWT_TIMEOUT_MS          100U
#define DW_RESET_DELAY_MS       15U
```

---

## 4. DS-TWR通信流程

### 4.1 完整的三次握手

```
Tag                                    Anchor
 |                                        |
 |  1. POLL (t_tx1)                       |
 |--------------------------------------->|
 |                                        | (t_rx1)
 |                                        |
 |                                        | 等待 ANCHOR_RESP_DELAY_US (1000μs)
 |                                        |
 |                        2. RESP (t_tx2) |
 |<---------------------------------------|
 | (t_rx2)                                |
 |                                        |
 | 等待 TAG_FINAL_DELAY_US (1500μs)        |
 |                                        |
 |  3. FINAL (t_tx3)                      |
 |--------------------------------------->|
 |                                        | (t_rx3)
 |                                        |
 |                                        | 计算距离
 |                                        |
 |                        4. FACK (距离)   |
 |<---------------------------------------|
 | (t_rx4)                                |
 |                                        |
 | 计算距离验证                              |
```

### 4.2 时间戳对应关系

| 变量 | 含义 | 记录位置 | 用途 |
|------|------|---------|------|
| `t_tx1` | Tag发送POLL时间 | Tag | tRound1, tReply2 |
| `t_rx1` | Anchor收到POLL时间 | Anchor | tRound1, tReply1 |
| `t_tx2` | Anchor发送RESP时间 | Anchor | tReply1, tRound2 |
| `t_rx2` | Tag收到RESP时间 | Tag | tRound2, tReply2 |
| `t_tx3` | Tag发送FINAL时间 | Tag | tReply2 |
| `t_rx3` | Anchor收到FINAL时间 | Anchor | tRound2 |

### 4.3 距离计算公式

```c
// Anchor侧计算（在收到FINAL后）
uint64_t tRound1 = t_rx1 - t_tx1;  // Anchor视角：收到-发出
uint64_t tReply1 = t_tx2 - t_rx1;  // Anchor响应时间
uint64_t tRound2 = t_rx3 - t_tx2;  // Tag响应时间（从Anchor视角）
uint64_t tReply2 = t_tx3 - t_rx2;  // Tag视角：发出-收到

double tof_dtu = (double)(tRound1 * tRound2 - tReply1 * tReply2) /
                 (double)(tRound1 + tRound2 + tReply1 + tReply2);

double distance_m = tof_dtu * DWT_TIME_UNITS * SPEED_OF_LIGHT;
```

---

## 5. 状态机统一

### 5.1 Tag状态机

```c
typedef enum {
    TAG_ST_IDLE = 0,      // 空闲，等待发送POLL
    TAG_ST_POLL_TX,       // 正在发送POLL
    TAG_ST_WAIT_RESP,     // 等待RESP
    TAG_ST_FINAL_TX,      // 正在发送FINAL
    TAG_ST_WAIT_FACK      // 等待FACK
} tag_state_t;
```

**状态转换**:
```
IDLE → POLL_TX → WAIT_RESP → FINAL_TX → WAIT_FACK → IDLE
  ↑                  ↓           ↓          ↓
  └──────超时────────┴───────────┴──────────┘
```

### 5.2 Anchor状态机

```c
typedef enum {
    ANCHOR_ST_IDLE = 0,       // 空闲
    ANCHOR_ST_RESP_SCHED,     // 准备发送RESP
    ANCHOR_ST_WAIT_FINAL,     // 等待FINAL
    ANCHOR_ST_FACK_SCHED      // 准备发送FACK
} anchor_state_t;
```

**状态转换**:
```
IDLE → RESP_SCHED → WAIT_FINAL → FACK_SCHED → IDLE
  ↑                      ↓
  └──────超时────────────┘
```

---

## 6. 重试策略

### 6.1 Tag重试配置

```c
static const tx_cfg_t s_tag_tx_poll = {
    .retry_step = FINAL_CHAIN_GAP_US,  // 600μs
    .max_retry = 2                      // 最多重试2次
};

static const tx_cfg_t s_tag_tx_final = {
    .retry_step = FINAL_CHAIN_GAP_US,  // 600μs
    .max_retry = 2
};
```

### 6.2 Anchor重试配置

```c
static const tx_cfg_t s_acr_tx_resp = {
    .retry_step = FINAL_CHAIN_GAP_US,  // 600μs
    .max_retry = 2
};

static const tx_cfg_t s_acr_tx_final = {
    .retry_step = FINAL_CHAIN_GAP_US,  // 600μs（已修复）
    .max_retry = 2
};
```

### 6.3 重试时序

```
第1次发送: t0
第1次重试: t0 + 600μs
第2次重试: t0 + 1200μs
放弃:      t0 + 1800μs
```

---

## 7. 超时配置总结

| 场景 | 超时时间 | 定义位置 | 说明 |
|------|---------|---------|------|
| Tag等待RESP | 6000μs | RESP_WINDOW_US | 包含Anchor延迟和传输时间 |
| Tag等待FACK | 6000μs | ACK_WINDOW_US | 包含Anchor计算和传输时间 |
| Anchor等待FINAL | 6000μs | RESP_WINDOW_US | 包含Tag延迟和传输时间 |
| Anchor GC - IDLE | 10ms | 代码 | 快速清理空闲事务 |
| Anchor GC - RESP_SCHED | 50ms | 代码 | 调度窗口超时 |
| Anchor GC - WAIT_FINAL | 6100ms | RESP_WINDOW_US/1000+100 | 协议窗口+余量 |
| Anchor GC - FACK_SCHED | 50ms | 代码 | 调度窗口超时 |

---

## 8. 调试日志规范

### 8.1 Tag日志标记

```c
"[POLL-TX]"           // 发送POLL
"[RESP-RX]"           // 收到RESP
"[FINAL-TX]"          // 发送FINAL
"[FACK-RX]"           // 收到FACK
"[RESP-TO]"           // RESP超时
"[FACK-TO]"           // FACK超时
"[RX-TO-UNEXPECTED]"  // 异常RX超时
"[RX-TO-UNKNOWN]"     // 未知状态RX超时
```

### 8.2 Anchor日志标记

```c
"[POLL-RX]"     // 收到POLL
"[RESP-TX]"     // 发送RESP
"[FINAL-RX]"    // 收到FINAL
"[FACK-TX]"     // 发送FACK
"[GC]"          // 垃圾回收清理事务
```

---

## 9. 验证清单

在修改后，请验证以下内容：

### 9.1 编译验证
- [ ] 代码能够成功编译
- [ ] 没有警告信息
- [ ] 所有配置常量都正确引用

### 9.2 功能验证
- [ ] Tag能够成功发送POLL
- [ ] Anchor能够正确响应RESP
- [ ] Tag能够正确发送FINAL
- [ ] Anchor能够计算距离并发送FACK
- [ ] 距离计算结果正确

### 9.3 协议验证
- [ ] 延迟时间符合配置（使用示波器或逻辑分析仪）
- [ ] 超时窗口正确触发
- [ ] 重试策略正确工作
- [ ] 垃圾回收及时清理过期事务

### 9.4 异常处理验证
- [ ] 丢包情况下能够正确重试
- [ ] 超时后能够正确恢复
- [ ] 异常状态有明确日志
- [ ] 资源能够正确释放

---

## 10. 未来改进建议

### 10.1 短期改进
- [ ] 添加统计信息（成功率、平均延迟等）
- [ ] 增加更详细的错误码
- [ ] 优化日志输出格式（减少串口负载）

### 10.2 中期改进
- [ ] 实现动态超时调整（根据信道质量）
- [ ] 添加拥塞控制机制
- [ ] 支持多Tag并发测距优化

### 10.3 长期改进
- [ ] 实现时钟漂移补偿
- [ ] 添加温度校准支持
- [ ] 支持AoA/AoD角度测量

---

## 11. 参考资料

### 11.1 相关文件
- `Core/Src/UWB/bu03.c` - 主实现文件
- `Core/Src/UWB/uwb_protocol_config.h` - 协议配置
- `Core/Src/UWB/uwb_frame.h` - 帧格式定义

### 11.2 DW1000文档
- DW1000 User Manual
- DW1000 API Guide
- DS-TWR Application Note

### 11.3 修改历史
- 2025-01-17: 初始版本 - 修复编译错误和协议不一致
- 2025-01-17: 改进超时处理和状态机
- 2025-01-17: 统一重试策略

---

**文档维护者**: Claude Code
**最后更新**: 2025-01-17
