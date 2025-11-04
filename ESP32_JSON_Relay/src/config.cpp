#include "config.h"

/**
 * 默认配置
 * 修改这些值可快速切换 Wi-Fi / UART 模式 / 端口等
 */
AppConfig appConfig = {
  // Wi-Fi 信息
  .wifi_ssid = "pzs",          // ← 改成你的热点名
  .wifi_pass = "88888888",     // ← 改成你的密码

  // 输入源选择
  .input_from_usb = false,        // false = 从 UART1 接收 STM32 数据
                                 // true  = 从 USB 串口接收 (电脑)
  .baud = 115200,                 // 波特率 (需与 STM32 一致)
  .uart_rx = 16,                  // UART1 RX 引脚
  .uart_tx = 17,                  // UART1 TX 引脚

  // TCP 端口
  .port_good = 9000,              // 合法 JSON 输出
  .port_bad  = 9001,              // 不合法 JSON 输出（调试）

  // 缓冲 & 调试
  .line_cap = 16384,              // 行缓存长度
  .verbose = true                 // true = 打印详细日志
};
