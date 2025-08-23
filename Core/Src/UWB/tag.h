#ifndef UWB_TRANS_TAG_H
#define UWB_TRANS_TAG_H

#ifdef __cplusplus
extern "C" {
#endif

void tag_init(void);
void tag_process(void);
void tag_set_rate_hz(float rate);

#ifdef __cplusplus
}
#endif

#endif /* UWB_TRANS_TAG_H */
