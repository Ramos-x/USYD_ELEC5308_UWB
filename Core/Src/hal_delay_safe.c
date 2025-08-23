#include "stm32f1xx_hal.h"

/*
 * 强覆盖 HAL_Delay：
 * - 优先按 HAL_GetTick 正常等待；
 * - 若检测到 Tick 不前进（可能是 SysTick 未运行或中断被关），则退化为基于 SystemCoreClock 的近似忙等，
 *   并按毫秒逐步递减，保证不会无限阻塞在 HAL_Delay。
 *
 * 说明：HAL 库中 HAL_Delay 通常为 __weak，可在用户代码中提供强符号进行覆盖。
 */

extern uint32_t SystemCoreClock;

static void busy_wait_ms_approx(uint32_t ms) {
    /* 简单近似：每毫秒执行一定次数的 NOP 循环，避免完全空转过快 */
    uint32_t loops = (SystemCoreClock / 8000U) * ms + 1U; /* 经验系数，非精准延时 */
    for (volatile uint32_t i = 0; i < loops; ++i) {
        __NOP();
    }
}

void HAL_Delay(uint32_t Delay) {
    if (Delay == 0U) {
        return;
    }

    uint32_t start = HAL_GetTick();
    uint32_t last  = start;
    uint32_t remaining = Delay;

    while (remaining > 0U) {
        uint32_t now = HAL_GetTick();

        if (now != last) {
            /* Tick 正常前进：按实际前进的毫秒数扣减 */
            uint32_t elapsed = now - last;
            if (elapsed > remaining) {
                elapsed = remaining;
            }
            remaining -= elapsed;
            last = now;
        } else {
            /* 未观察到 Tick 前进：执行一次近似 1ms 忙等作为兜底 */
            busy_wait_ms_approx(1U);

            uint32_t now2 = HAL_GetTick();
            if (now2 == last) {
                /* Tick 仍未动，主动扣减 1ms，防止死等 */
                if (remaining > 0U) {
                    remaining--;
                }
            } else {
                /* Tick 恢复：继续按 Tick 方式扣减 */
                last = now2;
            }
        }

        __NOP(); /* 轻量让步，尽量不影响中断 */
    }
}
