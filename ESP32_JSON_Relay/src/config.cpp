#include "config.h"

/** Config */
AppConfig appConfig = {
  /* wifi_ssid      */ "pzs",
  /* wifi_pass      */ "88888888",

  /* input_from_usb */ false,      // true=USB(Serial)；false=UART1(GPIO16/17)
  /* baud           */ 2000000,
  /* uart_rx        */ 16,
  /* uart_tx        */ 17,

  /* port_good      */ 9000,
  /* port_bad       */ 9001,

  /* line_cap       */ 16384,     // 你的日志比较长，16KB 够用；可调大
  /* verbose        */ false       //
};
