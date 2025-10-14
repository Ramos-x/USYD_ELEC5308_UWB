#pragma once
#include <Arduino.h>

/** 运行时配置（放这儿，便于集中修改/版本管理） */
struct AppConfig {
    // Wi-Fi
    const char* wifi_ssid;
    const char* wifi_pass;

    // 输入源：true=USB(Serial)，false=UART1(GPIO16/17)
    bool        input_from_usb;

    // 串口参数（USB 也会用到 baud 作为提示，无伤大雅）
    uint32_t    baud;
    int         uart_rx;   // e.g. 16
    int         uart_tx;   // e.g. 17

    // TCP 端口
    uint16_t    port_good; // 合法 JSON
    uint16_t    port_bad;  // 非法/解析失败 JSON

    // 行缓冲大小（按需调大/调小）
    size_t      line_cap;

    // 调试输出
    bool        verbose;
};

// 全局配置实例（在 config.cpp 里定义）
extern AppConfig appConfig;
