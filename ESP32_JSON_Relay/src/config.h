#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

/**
 * 全局配置结构体
 * 统一管理 Wi-Fi、UART、TCP、缓冲等参数
 */
struct AppConfig {
    // ===== Wi-Fi =====
    const char* wifi_ssid;
    const char* wifi_pass;

    // ===== 输入源 =====
    bool input_from_usb;    // true = USB Serial, false = UART1
    uint32_t baud;          // 波特率（USB与UART通用）
    int uart_rx;            // UART1 RX 引脚
    int uart_tx;            // UART1 TX 引脚

    // ===== TCP 端口 =====
    uint16_t port_good;     // 合法 JSON 输出端口
    uint16_t port_bad;      // 不合法 JSON 输出端口

    // ===== 缓冲设置 =====
    size_t line_cap;        // 行缓冲容量
    bool verbose;           // 输出调试信息
};

// 声明全局配置实例（定义在 config.cpp 中）
extern AppConfig appConfig;

#endif
