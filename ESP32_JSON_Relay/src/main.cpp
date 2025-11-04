#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include "config.h"  // ✅ 引入全局配置结构

 // ========================= 全局资源 =========================
HardwareSerial Uart(1);
WiFiServer goodSrv(appConfig.port_good), badSrv(appConfig.port_bad);
WiFiClient goodCli[5], badCli[2];

StaticJsonDocument<4096> doc;
char* lineBuf = nullptr;
size_t lineLen = 0;

// ========================= JSON 校验 =========================
bool schemaOK(const char* s, size_t len) {
    doc.clear();
    auto e = deserializeJson(doc, s, len);
    if (e) return false;
    if (!doc.is<JsonObject>()) return false;
    if (!doc.containsKey("role") || strcmp(doc["role"], "tag") != 0) return false;
    if (!doc.containsKey("anchors") || !doc["anchors"].is<JsonArray>()) return false;
    return true;
}

// ========================= TCP 客户端管理 =========================
void acceptNew(WiFiServer& srv, WiFiClient* pool, int n) {
    if (!srv.hasClient()) return;
    for (int i = 0; i < n; i++) {
        if (!pool[i] || !pool[i].connected()) {
            if (pool[i]) pool[i].stop();
            pool[i] = srv.available();
            if (pool[i]) {
                pool[i].setNoDelay(true);
                if (appConfig.verbose)
                    Serial.printf("[TCP] New client on port %u\n",
                        (srv == goodSrv ? appConfig.port_good : appConfig.port_bad));
            }
            return;
        }
    }
    WiFiClient drop = srv.available();
    drop.stop();
}

void broadcast(WiFiClient* pool, int n, const char* data, size_t len) {
    for (int i = 0; i < n; i++) {
        if (pool[i] && pool[i].connected()) {
            pool[i].write((const uint8_t*)data, len);
        }
        else if (pool[i]) {
            pool[i].stop();
        }
    }
}

// ========================= Wi-Fi 自动重连 =========================
void checkWiFi() {
    static unsigned long lastCheck = 0;
    if (millis() - lastCheck < 3000) return;  // 每3秒检查一次
    lastCheck = millis();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] ⚠️ Disconnected, reconnecting...");
        WiFi.disconnect();
        WiFi.begin(appConfig.wifi_ssid, appConfig.wifi_pass);

        unsigned long start = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - start < 5000) {
            delay(500);
            Serial.print(".");
        }

        if (WiFi.status() == WL_CONNECTED) {
            Serial.printf("\n[WiFi] ✅ Reconnected, IP: %s\n",
                WiFi.localIP().toString().c_str());
        }
        else {
            Serial.println("\n[WiFi] ❌ Still disconnected");
        }
    }
}

// ========================= 初始化 =========================
void setup() {
    Serial.begin(appConfig.baud);
    Serial.println("\n[BOOT] ESP32 JSON TCP Relay (Modular Config)");

    // 分配缓冲区
    lineBuf = new char[appConfig.line_cap];
    lineLen = 0;

    // ===== Wi-Fi =====
    WiFi.mode(WIFI_STA);
    WiFi.begin(appConfig.wifi_ssid, appConfig.wifi_pass);
    Serial.printf("[WiFi] Connecting to %s", appConfig.wifi_ssid);
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print(".");
    }
    Serial.printf("\n[WiFi] ✅ Connected, IP: %s\n",
        WiFi.localIP().toString().c_str());

    // ===== 串口输入源 =====
    if (appConfig.input_from_usb) {
        Serial.println("[UART] Using USB Serial as input");
    }
    else {
        Uart.begin(appConfig.baud, SERIAL_8N1, appConfig.uart_rx, appConfig.uart_tx);
        Uart.setRxBufferSize(32768);
        Serial.printf("[UART] RX=%d TX=%d BAUD=%lu\n", appConfig.uart_rx,
            appConfig.uart_tx, appConfig.baud);
    }

    // ===== TCP =====
    goodSrv.begin();
    badSrv.begin();
    goodSrv.setNoDelay(true);
    badSrv.setNoDelay(true);
    Serial.printf("[TCP] GOOD:%u  BAD:%u\n", appConfig.port_good, appConfig.port_bad);
}

// ========================= 主循环 =========================
void loop() {
    checkWiFi();  // 自动 Wi-Fi 检查与重连

    acceptNew(goodSrv, goodCli, 5);
    acceptNew(badSrv, badCli, 2);

    // 从输入源读取
    Stream* input = appConfig.input_from_usb ? (Stream*)&Serial : (Stream*)&Uart;

    while (input->available() > 0) {
        int c = input->read();
        Serial.write(c);  // 原始监控输出
        if (c < 0) break;
        if (c == '\r') continue;

        if (c == '\n') {
            lineBuf[lineLen] = '\0';
            if (lineLen > 10) {
                bool ok = schemaOK(lineBuf, lineLen);
                lineBuf[lineLen++] = '\n';
                if (ok) broadcast(goodCli, 5, lineBuf, lineLen);
                else    broadcast(badCli, 2, lineBuf, lineLen);
            }
            lineLen = 0;
            delayMicroseconds(500);
        }
        else if (lineLen < appConfig.line_cap - 2) {
            lineBuf[lineLen++] = (char)c;
        }
        else {
            lineLen = 0;  // 缓冲溢出重置
        }
    }
}
