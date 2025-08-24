#ifndef UWB_TRANS_TAG_H
#define UWB_TRANS_TAG_H

#ifdef __cplusplus
extern "C" {

#endif

void tag_init(void);

void tag_process(void);

void tag_set_rate_hz(float rate);

/* 基于芯片唯一ID随机化 Tag 的16位短地址（保证不同设备不重复） */
void tag_randomize_short(void);

/* 获取当前 Tag 的16位短地址 */
uint16_t tag_get_short(void);

#ifdef __cplusplus
}
#endif

#endif /* UWB_TRANS_TAG_H */
