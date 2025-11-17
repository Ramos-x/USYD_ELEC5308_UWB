# STM32 UWB固件优化报告

## 概述

本文档记录了对Core目录中STM32F103 UWB固件代码的优化工作。

---

## 发现的严重问题

### CRITICAL优先级

#### 1. 缓冲区溢出风险

**问题1.1**: 不安全的`sprintf`使用
- **文件**: `Core/Src/UWB/anchor.c:161`
- **问题**: 使用`sprintf`可能导致缓冲区溢出
- **修复**: ✅ 已改用`snprintf`

**问题1.2**: 巨大的栈缓冲区
- **文件**: `Core/Src/UWB/bu03.c:1135`
- **问题**: 2048字节栈缓冲区在STM32F1上占用栈空间的2/3
- **风险**: 栈溢出导致系统崩溃
- **修复**: 🔧 将改用静态缓冲区

#### 2. 中断安全性问题

**问题2.1**: 中断开关嵌套不安全
- **文件**: `Core/Src/UWB/bu03.c:64-88`
- **问题**: 在循环中重复调用`__disable_irq()`/`__enable_irq()`
- **风险**: 嵌套导致中断被意外重启
- **建议**: 使用HAL临界区宏或记录嵌套级别

**问题2.2**: 64位全局变量竞态条件
- **文件**: `Core/Src/UWB/bu03.c:225-242`
- **问题**: 64位`volatile`变量在ARM Cortex-M3上非原子读写
- **风险**: ISR和主线程间的竞态条件
- **建议**: 使用临界区保护或拆分为32位变量

**问题2.3**: 环形缓冲区指针竞态
- **文件**: `Core/Src/UWB/bu03.c:22-26`
- **问题**: `tx_head`/`tx_tail`在ISR和主线程间共享但保护不足
- **风险**: 数据丢失或重复

#### 3. 缺乏错误处理

**问题3.1**: DWT API调用未检查返回值
- **文件**: `Core/Src/UWB/bu03.c` (超过50处)
- **示例**: `dwt_writetxfctrl()`, `dwt_starttx()`, `dwt_setrxaftertxdelay()`
- **风险**: 操作失败导致无声故障
- **建议**: 添加返回值检查和错误日志

---

### HIGH优先级

#### 4. 协议参数不同步

**问题4.1**: TAG_FINAL_DELAY_US值不一致
- `bu03.c:229`: `#define FINAL_DELAY_US 1500U`
- `tag.c:35`: `#define TAG_FINAL_DELAY_US 2000U`
- `anchor.c:28`: `#define TAG_FINAL_DELAY_US 2000U`
- **风险**: 协议超时失败
- **修复**: ✅ 已创建`uwb_protocol_config.h`统一配置

#### 5. 无检查的memcpy

**问题5.1**: memcpy未验证目标缓冲区大小
- **文件**: `uwb_frames.c:38,39,56,57`
- **文件**: `bu03.c:78,83,576,974`
- **风险**: 缓冲区溢出
- **建议**: 添加边界检查或使用安全版本

#### 6. 数组越界

**问题6.1**: 轮询索引未检查
- **文件**: `bu03.c:814`
- **代码**: `const uint16_t dest = s_poll_targets[s_target_idx];`
- **建议**: 添加边界检查或使用模运算

---

## 优化措施

### 已完成的优化

#### 1. ✅ 创建统一协议配置文件

**文件**: `Core/Src/UWB/uwb_protocol_config.h`

**内容**:
- 所有协议时序参数（FINAL_DELAY_US, RESP_WINDOW_US等）
- 缓冲区大小配置
- 天线延迟参数
- 编译时检查

**优势**:
- 消除硬编码
- 确保Tag和Anchor使用相同参数
- 集中管理配置
- 编译时验证

#### 2. ✅ 修复sprintf缓冲区溢出

**文件**: `Core/Src/UWB/anchor.c:161`

**修改**:
```c
// 之前
for (int i = 0; i < 5; ++i) sprintf(out + 2 * i, "%02X", b[4 - i]);

// 之后
for (int i = 0; i < 5; ++i) {
    snprintf(out + 2 * i, 3, "%02X", b[4 - i]);
}
```

---

### 计划的优化

#### 3. 🔧 修复大栈缓冲区

**文件**: `Core/Src/UWB/bu03.c:1135`

**当前问题**:
```c
void try_flush_json(void) {
    char out[2048];  // ⚠️ 2KB栈分配
    // ... 复杂的JSON格式化
}
```

**优化方案**:
```c
// 方案A: 使用静态缓冲区（推荐）
static char s_json_output_buf[2048];  // 移至BSS段

void try_flush_json(void) {
    char *out = s_json_output_buf;
    // ... 使用静态缓冲区
}

// 方案B: 减小缓冲区 + 分块输出
#define JSON_BUF_SIZE 512
char out[JSON_BUF_SIZE];
// 分多次输出
```

**推荐**: 方案A，使用静态缓冲区

#### 4. 🔧 改进中断安全性

**修复uart1_write_bytes中的中断嵌套**:

```c
// 当前代码（不安全）
__disable_irq();
free = uart1_tx_free();
if (free == 0) {
    __enable_irq();  // ⚠️ 嵌套问题
    HAL_Delay(0);
}

// 优化方案：使用HAL临界区
uint32_t primask;
primask = __get_PRIMASK();
__disable_irq();

// 临界区操作
free = uart1_tx_free();

__set_PRIMASK(primask);  // 恢复中断状态
```

#### 5. 🔧 添加DWT错误处理

**在关键DWT调用添加检查**:

```c
// 示例：检查发送结果
int result = dwt_starttx(DWT_START_TX_DELAYED | DWT_RESPONSE_EXPECTED);
if (result != DWT_SUCCESS) {
    // 记录错误并恢复
    error_log("dwt_starttx failed");
    // 状态恢复逻辑
}
```

#### 6. 🔧 修复环形缓冲区竞态

**改进方案**:
```c
// 使用临界区保护
static inline uint16_t uart1_tx_used_safe(void) {
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    uint16_t h = tx_head, t = tx_tail;
    __set_PRIMASK(primask);
    return (h >= t) ? (h - t) : (UART1_TX_BUF_SZ - (t - h));
}
```

---

## 优化优先级

### 立即修复（CRITICAL）

1. ✅ sprintf -> snprintf（已完成）
2. 🔧 大栈缓冲区 -> 静态缓冲区
3. 🔧 中断开关嵌套问题
4. 🔧 添加DWT错误处理

### 短期修复（HIGH）

5. ✅ 统一协议参数（已完成）
6. 🔧 添加memcpy边界检查
7. 🔧 数组索引边界检查
8. 🔧 环形缓冲区竞态保护

### 中期改进（MEDIUM）

9. 函数拆分（tag_on_rx_ok, try_flush_json）
10. 添加NULL指针检查
11. 改进日志队列
12. 代码重复消除

---

## 测试建议

### 单元测试

- [ ] 环形缓冲区边界条件测试
- [ ] JSON格式化溢出测试
- [ ] 中断嵌套压力测试

### 集成测试

- [ ] 多Anchor通信测试
- [ ] 长时间运行稳定性测试
- [ ] 错误注入测试（DWT失败场景）

### 性能测试

- [ ] 栈使用分析
- [ ] 中断延迟测量
- [ ] 内存使用分析

---

## 风险评估

### 修改风险

| 修改项 | 风险等级 | 影响范围 | 测试要求 |
|--------|---------|---------|---------|
| sprintf->snprintf | 低 | 局部 | 基本 |
| 栈->静态缓冲区 | 低 | 局部 | 基本 |
| 中断保护改进 | 中 | 全局 | 详细 |
| DWT错误处理 | 中 | 核心逻辑 | 详细 |
| 协议参数统一 | 高 | 协议兼容性 | 完整 |

### 向后兼容性

- ✅ sprintf->snprintf: 完全兼容
- ✅ 静态缓冲区: 完全兼容
- ⚠️ 协议参数: 需要同时更新所有设备
- ⚠️ DWT错误处理: 可能改变错误行为

---

## 后续工作

### 架构改进

1. **模块化重构**
   - 拆分bu03.c为多个模块
   - 创建独立的环形缓冲区库
   - 统一UART抽象层

2. **错误处理框架**
   - 定义错误代码枚举
   - 实现错误日志系统
   - 添加错误恢复机制

3. **代码复用**
   - 提取公共的ts40_to_hex函数
   - 统一UART环形缓冲实现
   - 共享的工具函数库

### 性能优化

1. **中断优化**
   - 减少ISR执行时间
   - 使用DMA代替轮询
   - 优化临界区大小

2. **内存优化**
   - 减少栈使用
   - 优化静态缓冲区
   - 使用内存池

3. **功耗优化**
   - 添加睡眠模式
   - 优化轮询周期
   - DW1000功耗管理

---

## 版本历史

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| 1.0 | 2025-01-17 | 初始分析和优化方案 |
| 1.1 | 2025-01-17 | 修复sprintf，创建协议配置文件 |

---

## 附录

### A. 编译检查

建议在编译时启用更多警告：

```makefile
CFLAGS += -Wall -Wextra -Werror
CFLAGS += -Wstack-usage=512  # 警告栈使用超过512字节的函数
CFLAGS += -Wundef            # 未定义宏
CFLAGS += -Wcast-align       # 对齐问题
```

### B. 静态分析工具

推荐使用的工具：
- **Cppcheck**: 静态代码分析
- **PC-lint**: 商业静态分析工具
- **Clang Static Analyzer**: 深度分析

### C. 参考文档

- STM32F103参考手册
- DW1000用户手册
- ARM Cortex-M3编程手册
- IEEE 802.15.4标准

---

**优化负责人**: Claude AI
**最后更新**: 2025-01-17
