#ifndef UWB_FRAMES_H
#define UWB_FRAMES_H

#include <stdint.h>
#include <stddef.h>

/* ---------- 消息类型 ---------- */
#define UWB_MSG_POLL   0x01
#define UWB_MSG_RESP   0x02
#define UWB_MSG_FINAL  0x03

/* ---------- 802.15.4 帧控制字（FCF） ----------
 * Data Frame + PAN Compression + Dest16 + Src16
 * NOTE: 在内存里是小端 0x8841，发出去字节顺序就是 41 88
 */
#define MAC_FCF_DATA_PANCOMP_SHORT  0x8841u

/* ---------- 打包属性（避免结构体填充） ---------- */
#if defined(__GNUC__) || defined(__clang__) || defined(__ICCARM__)
#define PACKED __attribute__((packed))
#else
#define PACKED
#endif

#if defined(_MSC_VER)
#pragma pack(push,1)
#endif

/* 802.15.4 短地址帧头（PAN 压缩）= 9 字节 */
typedef struct PACKED {
    uint16_t fcf; /* = MAC_FCF_DATA_PANCOMP_SHORT (小端常量) */
    uint8_t seq; /* 序号 */
    uint16_t pan; /* PAN ID */
    uint16_t dest; /* 目的短地址 */
    uint16_t src; /* 源短地址 */
} mac_hdr_short_t;

/* 负载：POLL/RESP/FINAL */
typedef struct PACKED {
    uint8_t msg; /* = UWB_MSG_POLL */
} pl_poll_t;

typedef struct PACKED {
    uint8_t msg; /* = UWB_MSG_RESP */
    uint8_t t_rx1[5]; /* Responder 收到 POLL 的时刻 (T2)  */
    uint8_t t_tx2[5]; /* Responder 发送 RESP 的时刻 (T3)  */
} pl_resp_t;

typedef struct PACKED {
    uint8_t msg; /* = UWB_MSG_FINAL */
    uint8_t t_tx1[5]; /* Initiator 发送 POLL 的时刻 (T1) */
    uint8_t t_rx2[5]; /* Initiator 收到 RESP 的时刻 (T4) */
    uint8_t t_tx3[5]; /* Initiator 发送 FINAL 的时刻 (T5) */
} pl_final_t;

#if defined(_MSC_VER)
#pragma pack(pop)
#endif

/* 解析后的视图 */
typedef struct {
    const mac_hdr_short_t *hdr; /* 指向输入缓冲区中的帧头 */
    const void *payload; /* 指向输入缓冲区中的负载起始 */
    uint16_t payload_len; /* 负载长度（不含 FCS） */
} uwb_frame_view_t;

/* ---------- 工具函数（时间戳 5B <-> 64b） ---------- */
#ifdef __cplusplus
extern "C" {

#endif

/* 将 64b 时间戳写成 5 字节（低 40bit 有效，DW 硬件格式） */
void uwb_ts64_to_40(uint64_t t, uint8_t out5[5]);

/* 从 5 字节（低 40bit）读回 64b（高位填 0） */
uint64_t uwb_ts40_to_64(const uint8_t in5[5]);

/* ---------- 帧头填充 ---------- */
void uwb_mac_hdr_fill(mac_hdr_short_t *h,
                      uint8_t seq, uint16_t pan,
                      uint16_t dest, uint16_t src);

/* ---------- 组帧（返回：MAC 帧长度 = 头 + 负载；不含 FCS） ----------
 * 使用 dwt_writetxfctrl(len + 2, ..., rng=1) 记得 +2 表示 FCS！
 */
uint16_t uwb_build_poll(uint8_t *buf,
                        uint8_t seq, uint16_t pan,
                        uint16_t dest, uint16_t src);

uint16_t uwb_build_resp(uint8_t *buf,
                        uint8_t seq, uint16_t pan,
                        uint16_t dest, uint16_t src,
                        uint64_t t_rx1, uint64_t t_tx2);

uint16_t uwb_build_final(uint8_t *buf,
                         uint8_t seq, uint16_t pan,
                         uint16_t dest, uint16_t src,
                         uint64_t t_tx1, uint64_t t_rx2, uint64_t t_tx3);

/* ---------- 解帧 ----------
 * 0 成功；非 0 表示长度不足或 FCF 不匹配
 */
int uwb_parse_frame(const uint8_t *buf, uint16_t len, uwb_frame_view_t *out);

/* 获取负载中的消息类型；失败返回 0xFF */
uint8_t uwb_get_msg_type(const uwb_frame_view_t *v);

#ifdef __cplusplus
}
#endif

/* 一些便捷常量 */
enum {
    UWB_MAC_HDR_SIZE = 9
};

#endif /* UWB_FRAMES_H */
