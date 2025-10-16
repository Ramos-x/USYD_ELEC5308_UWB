/********************************************************************
 * ESP32 JSON Filter + TCP Relay (PlatformIO + CLion)
 *  - 从 USB(Serial) 或 UART1 接收 JSON 行
 *  - 校验 JSON 语法与结构
 *  - 合法 -> TCP:9000   不合法 -> TCP:9001
 *  - Wi-Fi/输入源/端口/缓冲 等在 config.cpp 中集中配置
 ********************************************************************/
#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include "config.h"

// ===== UART / 输入源 =====
HardwareSerial Uart(1);     // UART1: RX/TX 由配置指定
Stream* in = nullptr;       // 指向 Serial 或 Uart

// ===== TCP Server & Clients =====
WiFiServer goodSrv(appConfig.port_good);
WiFiServer badSrv(appConfig.port_bad);
WiFiClient goodCli[5], badCli[2];

// ===== 动态行缓冲 =====
static char*  lineBuf   = nullptr;
static size_t lineCap   = 0;
static size_t lineLen   = 0;

// ---------- 工具：HEX 校验 ----------
static inline bool isHex(const char* s) {
  if (!s || !*s) return false;
  for (const char* p = s; *p; ++p) {
    char c = *p;
    if (!((c >= '0' && c <= '9') ||
          (c >= 'a' && c <= 'f') ||
          (c >= 'A' && c <= 'F'))) return false;
  }
  return true;
}

// ---------- JSON schema 校验 ----------
static bool schemaOK(const char* s, size_t len) {
  StaticJsonDocument<4096> doc;
  auto e = deserializeJson(doc, s, len);
  if (e) return false;
  if (!doc.is<JsonObject>()) return false;

  // 顶层
  if (!doc.containsKey("role") || strcmp(doc["role"], "tag") != 0) return false;
  if (!doc.containsKey("tag")  || !doc["tag"].is<const char*>())   return false;
  if (!doc.containsKey("tick") || !doc["tick"].is<long>())         return false;
  if (!doc.containsKey("anchor_count") || !doc["anchor_count"].is<long>()) return false;
  if (!doc.containsKey("anchors") || !doc["anchors"].is<JsonArray>())      return false;

  JsonArray arr = doc["anchors"].as<JsonArray>();
  if ((long)arr.size() != doc["anchor_count"].as<long>()) return false;

  // 每个 anchor
  for (JsonVariant v : arr) {
    if (!v.is<JsonObject>()) return false;
    JsonObject a = v.as<JsonObject>();
    if (!a.containsKey("aid")      || !a["aid"].is<long>())           return false;
    if (!a.containsKey("aid_hex")  || !a["aid_hex"].is<const char*>())return false;
    if (!a.containsKey("tick")     || !a["tick"].is<long>())          return false;
    if (!a.containsKey("ts")       || !a["ts"].is<const char*>())     return false;
    if (!a.containsKey("ex")       || !a["ex"].is<JsonObject>())      return false;
    if (!a.containsKey("dt_us")    || !a["dt_us"].is<JsonObject>())   return false;
    if (!isHex(a["aid_hex"]) || !isHex(a["ts"])) return false;

    JsonObject ex = a["ex"].as<JsonObject>();
    const char* ks[] = {"tx1","rx1","tx2","rx2","tx3p","tx3r","rx3"};
    if (!ex.containsKey("seq")      || !ex["seq"].is<long>())      return false;
    if (!ex.containsKey("complete") || !ex["complete"].is<long>()) return false;
    int cpl = ex["complete"].as<long>(); if (!(cpl == 0 || cpl == 1)) return false;
    for (auto k : ks) {
      if (!ex.containsKey(k) || !ex[k].is<const char*>() || !isHex(ex[k])) return false;
    }

    JsonObject dt = a["dt_us"].as<JsonObject>();
    if (!dt.containsKey("tx1_rx2")   || !dt["tx1_rx2"].is<long>())   return false;
    if (!dt.containsKey("rx2_tx3p")  || !dt["rx2_tx3p"].is<long>())  return false;
    if (cpl == 1 && (!dt.containsKey("rx2_tx3r") || !dt["rx2_tx3r"].is<long>())) return false;
  }
  return true;
}

// ---------- TCP 辅助 ----------
static void acceptNew(WiFiServer& srv, WiFiClient* pool, int n) {
  if (!srv.hasClient()) return;
  for (int i = 0; i < n; i++) {
    if (!pool[i] || !pool[i].connected()) {
      if (pool[i]) pool[i].stop();
      pool[i] = srv.available();
      if (pool[i]) pool[i].setNoDelay(true);
      return;
    }
  }
  WiFiClient drop = srv.available();
  drop.stop();
}

static void broadcast(WiFiClient* pool, int n, const char* data, size_t len) {
  for (int i = 0; i < n; i++) {
    if (pool[i] && pool[i].connected()) {
      pool[i].write((const uint8_t*)data, len);
    } else if (pool[i]) {
      pool[i].stop();
    }
  }
}

// ---------- 打印当前配置 ----------
static void printConfig() {
  Serial.println();
  Serial.println("===== AppConfig =====");
  Serial.printf("WiFi   : SSID=%s\n", appConfig.wifi_ssid);
  Serial.printf("Input  : %s\n", appConfig.input_from_usb ? "USB(Serial)" : "UART1(GPIO16/17)");
  Serial.printf("Baud   : %lu\n", (unsigned long)appConfig.baud);
  Serial.printf("UART   : RX=%d TX=%d\n", appConfig.uart_rx, appConfig.uart_tx);
  Serial.printf("TCP    : GOOD=%u  BAD=%u\n", appConfig.port_good, appConfig.port_bad);
  Serial.printf("LineCap: %u bytes\n", (unsigned)appConfig.line_cap);
  Serial.printf("Verbose: %s\n", appConfig.verbose ? "on" : "off");
  Serial.println("=====================");
}

// ================== Arduino 生命周期 ==================
void setup() {
  Serial.begin(appConfig.baud);
  delay(50);

  // 动态行缓冲
  lineCap = appConfig.line_cap;
  lineBuf = (char*)malloc(lineCap);
  lineLen = 0;

  if (!lineBuf) {
    Serial.println("FATAL: malloc lineBuf failed");
    while (true) delay(1000);
  }

  if (appConfig.verbose) printConfig();

  // 选择输入源
  if (appConfig.input_from_usb) {
    in = &Serial;
    if (appConfig.verbose) Serial.println("[INPUT] USB Serial (电脑发送模式)");
  } else {
    Uart.begin(appConfig.baud, SERIAL_8N1, appConfig.uart_rx, appConfig.uart_tx);
    in = &Uart;
    if (appConfig.verbose) Serial.println("[INPUT] UART1 (STM32 模式)");
  }

  // Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(appConfig.wifi_ssid, appConfig.wifi_pass);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP: %s\n", WiFi.localIP().toString().c_str());

  // TCP
  goodSrv = WiFiServer(appConfig.port_good);
  badSrv  = WiFiServer(appConfig.port_bad);
  goodSrv.begin(); goodSrv.setNoDelay(true);
  badSrv.begin();  badSrv.setNoDelay(true);
  Serial.printf("TCP GOOD:%u  BAD:%u\n", appConfig.port_good, appConfig.port_bad);
}

void loop() {
  // 接新客户端
  acceptNew(goodSrv, goodCli, 5);
  acceptNew(badSrv,  badCli,  2);

  // 读一行（以 \n 结束）
  while (in->available() > 0) {
    int c = in->read();
    if (c < 0) break;
    if (c == '\r') continue;

    if ((size_t)lineLen >= lineCap - 2) {
      if (appConfig.verbose) Serial.println("⚠️ Line too long, buffer reset.");
      lineLen = 0;
      continue;
    }

    if (c == '\n') {
      // 完整一行
      lineBuf[lineLen] = '\0';

      if (appConfig.verbose) {
        Serial.println("📩 Received one JSON line:");
        Serial.println(lineBuf);
      }

      bool ok = schemaOK(lineBuf, lineLen);

      // 末尾补 \n 再转发
      lineBuf[lineLen++] = '\n';
      if (ok) {
        if (appConfig.verbose) Serial.println("✅ JSON parsed & schema OK");
        broadcast(goodCli, 5, lineBuf, lineLen);
      } else {
        if (appConfig.verbose) Serial.println("❌ JSON invalid or parse failed");
        broadcast(badCli,  2, lineBuf, lineLen);
      }
      lineLen = 0;
    } else {
      lineBuf[lineLen++] = (char)c;
    }
  }
}
