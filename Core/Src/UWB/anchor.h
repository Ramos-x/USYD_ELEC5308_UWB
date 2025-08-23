#ifndef UWB_TRANS_ANCHOR_H
#define UWB_TRANS_ANCHOR_H

#ifdef __cplusplus
extern "C" {
#endif

void anchor_init(void);
void anchor_process(void);
void anchor_set_rate_hz(float rate);

#ifdef __cplusplus
}
#endif

#endif /* UWB_TRANS_ANCHOR_H */
