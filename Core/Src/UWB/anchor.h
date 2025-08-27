#ifndef UWB_TRANS_ANCHOR_H
#define UWB_TRANS_ANCHOR_H

#ifdef __cplusplus
extern "C" {

#endif

void anchor_init(void);

void anchor_process(void);

void anchor_set_rate_hz(float rate);

static void uart1_printf(const char *fmt, ...);
/* 基于芯片唯一ID随机化 Anchor 的16位短地址（保证不同设备不重复） */
void anchor_randomize_short(void);

/* 获取当前 Tag 的16位短地址 */
uint16_t anchor_get_short(void);

#ifdef __cplusplus
}
#endif

#endif /* UWB_TRANS_ANCHOR_H */
