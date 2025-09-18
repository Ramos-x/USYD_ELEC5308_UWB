//
// Created by ramos on 2025/8/25.
//

#include "uwb_frames.h"
#include <string.h>

/* --- 工具：时间戳 5B <-> 64b --- */
void uwb_ts64_to_40(uint64_t t, uint8_t out5[5]) {
    for (int k = 0; k < 5; ++k) out5[k] = (uint8_t) ((t >> (8U * k)) & 0xFFU);
}

uint64_t uwb_ts40_to_64(const uint8_t in5[5]) {
    uint64_t t = 0;
    for (int k = 0; k < 5; ++k) t |= ((uint64_t) in5[k]) << (8U * k);
    return t;
}

/* --- 帧头填充 --- */
void uwb_mac_hdr_fill(mac_hdr_short_t *h,
                      uint8_t seq, uint16_t pan,
                      uint16_t dest, uint16_t src) {
    h->fcf = MAC_FCF_DATA_PANCOMP_SHORT; /* 小端常量 */
    h->seq = seq;
    h->pan = pan;
    h->dest = dest;
    h->src = src;
}

/* --- 组帧：POLL --- */
uint16_t uwb_build_poll(uint8_t *buf,
                        uint8_t seq, uint16_t pan,
                        uint16_t dest, uint16_t src) {
    mac_hdr_short_t hdr;
    pl_poll_t pl = {.msg = UWB_MSG_POLL};

    uwb_mac_hdr_fill(&hdr, seq, pan, dest, src);
    memcpy(buf, &hdr, sizeof(hdr));
    memcpy(buf + sizeof(hdr), &pl, sizeof(pl));

    return (uint16_t) (sizeof(hdr) + sizeof(pl));
}

/* --- 组帧：RESP --- */
uint16_t uwb_build_resp(uint8_t *buf,
                        uint8_t seq, uint16_t pan,
                        uint16_t dest, uint16_t src,
                        uint64_t t_rx1, uint64_t t_tx2) {
    mac_hdr_short_t hdr;
    pl_resp_t pl;
    pl.msg = UWB_MSG_RESP;
    uwb_ts64_to_40(t_rx1, pl.t_rx1);
    uwb_ts64_to_40(t_tx2, pl.t_tx2);

    uwb_mac_hdr_fill(&hdr, seq, pan, dest, src);
    memcpy(buf, &hdr, sizeof(hdr));
    memcpy(buf + sizeof(hdr), &pl, sizeof(pl));

    return (uint16_t) (sizeof(hdr) + sizeof(pl));
}

/* --- 组帧：FINAL --- */
uint16_t uwb_build_final(uint8_t *buf,
                         uint8_t seq, uint16_t pan,
                         uint16_t dest, uint16_t src,
                         uint64_t t_tx1, uint64_t t_rx2, uint64_t t_tx3) {
    mac_hdr_short_t hdr;
    pl_final_t pl;
    pl.msg = UWB_MSG_FINAL;
    uwb_ts64_to_40(t_tx1, pl.t_tx1);
    uwb_ts64_to_40(t_rx2, pl.t_rx2);
    uwb_ts64_to_40(t_tx3, pl.t_tx3);

    uwb_mac_hdr_fill(&hdr, seq, pan, dest, src);
    memcpy(buf, &hdr, sizeof(hdr));
    memcpy(buf + sizeof(hdr), &pl, sizeof(pl));

    return (uint16_t) (sizeof(hdr) + sizeof(pl));
}
uint16_t uwb_build_fack(uint8_t *buf,
                        uint8_t seq, uint16_t pan,
                        uint16_t dest, uint16_t src,
                        uint64_t t_rx3)
{
    mac_hdr_short_t hdr;
    pl_fack_t pl;
    pl.msg = UWB_MSG_FACK;
    uwb_ts64_to_40(t_rx3, pl.t_rx3);

    uwb_mac_hdr_fill(&hdr, seq, pan, dest, src);
    memcpy(buf, &hdr, sizeof(hdr));
    memcpy(buf + sizeof(hdr), &pl, sizeof(pl));

    return (uint16_t)(sizeof(hdr) + sizeof(pl));
}

/* --- 解帧 --- */
int uwb_parse_frame(const uint8_t *buf, uint16_t len, uwb_frame_view_t *out) {
    if (!buf || !out) return -1;
    if (len < sizeof(mac_hdr_short_t)) return -2;

    const mac_hdr_short_t *hdr = (const mac_hdr_short_t *) buf;
    if (hdr->fcf != MAC_FCF_DATA_PANCOMP_SHORT) return -3;

    out->hdr = hdr;
    out->payload = buf + sizeof(*hdr);
    out->payload_len = (uint16_t) (len - sizeof(*hdr));
    return 0;
}

uint8_t uwb_get_msg_type(const uwb_frame_view_t *v) {
    if (!v || v->payload_len == 0) return 0xFF;
    const uint8_t *p = (const uint8_t *) v->payload;
    return p[0];
}
