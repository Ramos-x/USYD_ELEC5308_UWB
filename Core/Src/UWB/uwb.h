#ifndef _UWB_H
#define _UWB_H

// #include "hal_spi.h" 被以下替代
#include "stm32f1xx_hal.h"
#include "deca_types.h"
#include "main.h"  // 使用 CubeMX 生成的引脚/端口宏

// #define DEV_ID_ID                   	(0x00)
#define DWT_DEVICE_ID               	(0xDECA0130)

#define DWT_SUCCESS                 	(0)
#define DWT_ERROR                   	(-1)

#define writetospi                  	writetospi_serial
#define readfromspi                		readfromspi_serial

// ========= HAL 适配（替换原 SPL 宏/符号）=========
// DW3000 中断引脚与片选映射（按你的 CubeMX 宏）
#define DW3000_IRQ_GPIO_Port            DW_IRQ_GPIO_Port
#define DW3000_IRQ_Pin                  DW_IRQ_Pin

#define DW3000_CS_GPIO_Port             SPI1_CSN_GPIO_Port
#define DW3000_CS_Pin                   SPI1_CSN_Pin

// PB5 -> EXTI5 属于 EXTI9_5_IRQn
#ifndef DW3000_IRQ_EXTI_IRQn
#define DW3000_IRQ_EXTI_IRQn            EXTI9_5_IRQn
#endif

// 读取 NVIC 中断使能状态（替代 EXTI_GetITEnStatus）
static inline uint32_t port_GetEXT_IRQStatus_impl(void) {
    uint32_t irqn = (uint32_t)DW3000_IRQ_EXTI_IRQn;
    uint32_t iser_index = irqn >> 5U;              // 每 32 个 IRQ 一组
    uint32_t iser_mask  = 1UL << (irqn & 0x1FU);
    return (NVIC->ISER[iser_index] & iser_mask) ? 1U : 0U;
}

// deca_mutex.c 期望的抽象接口（用 HAL 实现）
#define port_GetEXT_IRQStatus()         port_GetEXT_IRQStatus_impl()
// #define port_DisableEXT_IRQ()           NVIC_DisableIRQ(DW3000_IRQ_EXTI_IRQn)
// #define port_EnableEXT_IRQ()            NVIC_EnableIRQ(DW3000_IRQ_EXTI_IRQn)
#define port_CheckEXT_IRQ()             (HAL_GPIO_ReadPin(DW3000_IRQ_GPIO_Port, DW3000_IRQ_Pin) == GPIO_PIN_SET)

#define port_SPIx_set_chip_select()	    HAL_GPIO_WritePin(DW3000_CS_GPIO_Port, DW3000_CS_Pin, GPIO_PIN_SET)
#define port_SPIx_clear_chip_select()	HAL_GPIO_WritePin(DW3000_CS_GPIO_Port, DW3000_CS_Pin, GPIO_PIN_RESET)
// ========= 适配结束 =========

#define portGetTickCount() 				portGetTickCnt()

void port_DisableEXT_IRQ(void);
void port_EnableEXT_IRQ(void);
/**
 * @brief 软件延时计数（来自时基中断递增）
 */
extern __IO unsigned long time32_incr;

/**
 * @brief 毫秒级延时
 * @param time_ms: 延时毫秒数
 */
extern void Sleep(unsigned int time_ms);

/**
 * @brief 硬件复位 DW3000（要求 RSTn 已连接）
 */
extern void reset_DWIC(void);

/**
 * @brief 重新配置 SPI 时钟分频为较快速率
 * @param scalingfactor: 分频系数（平台相关）
 */
extern void SPI_ConfigFastRate(uint16_t scalingfactor);

/**
 * @brief 将 DW3000 SPI 速率设置为慢速（<3MHz，初始化/休眠前需要）
 */
extern void port_set_dw_ic_spi_slowrate(void);

/**
 * @brief 将 DW3000 SPI 速率设置为快速（正常工作）
 */
extern void port_set_dw_ic_spi_fastrate(void);

/**
 * @brief 毫秒延时（DW 驱动使用）
 * @param time_ms: 毫秒数
 */
extern void deca_sleep(unsigned int time_ms);

/**
 * @brief 配置 RSTn 与 IRQ 引脚模式
 * @param enable: 使能/失能
 */
extern void setup_DW1000RSTnIRQ(int enable);

/**
 * @brief 关闭 DW3000 外部中断
 */
extern void disable_deca_irq(void);

/**
 * @brief 使能 DW3000 外部中断
 */
extern void enable_deca_irq(void);

/**
 * @brief SPI 写（头+体），平台适配实现
 * @param headerLength  头部字节数
 * @param headerBuffer  头部数据
 * @param bodylength    数据体字节数
 * @param bodyBuffer    数据体
 * @return 0 成功，-1 失败
 */
extern int writetospi_serial(uint16_t headerLength,
                             const uint8_t *headerBuffer,
                             uint16_t bodylength,
                             const uint8_t *bodyBuffer);

/**
 * @brief SPI 读（先写头，再读数据），平台适配实现
 * @param headerLength  头部字节数
 * @param headerBuffer  头部数据（读操作的指令/地址等）
 * @param readlength    待读数据字节数
 * @param readBuffer    输出缓冲区
 * @return 0 成功，-1 失败
 */
extern int readfromspi_serial(uint16_t headerLength,
                              uint8_t *headerBuffer,
                              uint16_t readlength,
                              uint8_t *readBuffer);

/**
 * @brief 通过 IO 唤醒 DW3000（由 uwb 源文件实现）
 */
void wakeup_device_with_io(void);

/**
 * @brief 初始化 DW3000（唤醒、配置、回调注册、进入接收）
 * @return 0 成功；负值为错误码
 */
int UWB_DW3000_Init(void);

/**
 * @brief UWB 周期性任务（若为 Tag 角色则主动按周期发送 POLL）
 *        请在主循环中定期调用
 */
void uwb_periodic_task(void);

#endif