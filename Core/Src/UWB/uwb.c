#include "stm32f1xx_hal.h"
#include "uwb.h"
#include "deca_device_api.h"
#include "main.h"
#include "bu03.h"
#include "tag.h"


// ========== 端口层（唤醒/复位）==========

/**
 * @brief  通过 IO 唤醒 DW3000（常用 CS 脉冲方式）
 * @note   若硬件接有 WAKEUP 引脚，也可改为对 WAKEUP 输出脉冲
 *         唤醒后建议延时，确保内部上电稳定
 */
void wakeup_device_with_io() {
    /* 仅用 CS 唤醒：CS 低保持 ≥1ms，其后拉高并等待 ≥7ms */
    port_SPIx_clear_chip_select();
    HAL_Delay(1);
    port_SPIx_set_chip_select();
    HAL_Delay(7);
}


/**
 * @brief  对 DW3000 执行硬件复位（需连接 RSTn）
 * @note   若无 RSTn 连接，可改为软复位 dwt_softreset()
 */
void reset_DWIC() {
    HAL_GPIO_WritePin(DW_RSTN_GPIO_Port, DW_RSTN_Pin, GPIO_PIN_RESET);
    HAL_Delay(2);
    HAL_GPIO_WritePin(DW_RSTN_GPIO_Port, DW_RSTN_Pin, GPIO_PIN_SET);
    HAL_Delay(2);
}

void port_DisableEXT_IRQ(void) {
    HAL_NVIC_DisableIRQ(DW3000_IRQ_EXTI_IRQn); // 只关这一路
}

void port_EnableEXT_IRQ(void) {
    __HAL_GPIO_EXTI_CLEAR_IT(DW_IRQ_Pin);
    NVIC_ClearPendingIRQ(DW3000_IRQ_EXTI_IRQn);
    HAL_NVIC_EnableIRQ(DW3000_IRQ_EXTI_IRQn);
}

// ========== EXTI中断转发至 DW3000 ISR ==========
/**
 * @brief  HAL GPIO EXTI 回调：将 DW3000 中断转交给驱动 ISR
 * @param  GPIO_Pin: 触发的引脚号
 * @note   dwt_isr() 会完成状态清除与回调分发
 */
static volatile uint8_t g_dw_isr_busy = 0;

static inline void dw3000_isr_drain_all(void) {
    if (g_dw_isr_busy) return; // 防止重入
    g_dw_isr_busy = 1;
    while (dwt_checkirq()) {
        // 用驱动提供的检测
        dwt_isr(); // 读/清中断 + 分发回调
    }
    g_dw_isr_busy = 0;
}

void HAL_GPIO_EXTI_Callback(uint16_t pin) {
    if (pin == DW_IRQ_Pin) {
        HAL_NVIC_DisableIRQ(DW3000_IRQ_EXTI_IRQn);
        dw3000_isr_drain_all(); // 把所有挂起源“吃干净”
        __HAL_GPIO_EXTI_CLEAR_IT(DW_IRQ_Pin);
        NVIC_ClearPendingIRQ(DW3000_IRQ_EXTI_IRQn);
        HAL_NVIC_EnableIRQ(DW3000_IRQ_EXTI_IRQn);
    }
}

/**
 * @brief  EXTI9_5 中断服务函数：转发给 HAL 处理
 * @note   确保 NVIC 里已使能 EXTI9_5_IRQn
 */
void EXTI9_5_IRQHandler() {
    HAL_GPIO_EXTI_IRQHandler(DW_IRQ_Pin);
}

// ========== DW3000 初始化函数（C 接口导出） ==========

/**
 * @brief  UWB（DW3000）初始化：唤醒、基本配置、注册回调并进入接收
 * @return 0 成功；负值为错误
 *         -1: dwt_initialise 失败
 *         -2: dwt_configure 失败
 *         -3: 启动接收失败
 * @note   调用前需完成 SPI/GPIO/EXTI 初始化；默认关闭 STS
 */
int UWB_DW3000_Init() {
    /* 1) 初始化阶段强制 SPI 低速（<3MHz），满足 INIT_RC 要求 */
    port_set_dw_ic_spi_slowrate();

    HAL_Delay(10);

    /* 2) 唤醒与复位时序（两者至少执行其一；若连接了 RSTn 建议复位） */
    // wakeup_device_with_io();
    reset_DWIC();
    HAL_Delay(7); // 让内部稳态

    /* 3) 驱动初始化：此阶段仍保持低速 SPI，确保读 DEV_ID 成功 */
    if (dwt_initialise(0) != DWT_SUCCESS) {
        return -1;
    }

    dwt_config_t cfg;
    cfg.chan = 5;
    cfg.txPreambLength = DWT_PLEN_64;
    cfg.rxPAC = DWT_PAC8;
    cfg.txCode = 9;
    cfg.rxCode = 9;
    cfg.sfdType = DWT_SFD_IEEE_4A;
    cfg.dataRate = DWT_BR_6M8;
    cfg.phrMode = DWT_PHRMODE_STD;
    cfg.phrRate = DWT_PHRRATE_STD;
    cfg.sfdTO = DWT_SFDTOC_DEF;
    cfg.stsMode = DWT_STS_MODE_OFF;
    cfg.stsLength = DWT_STS_LEN_64;
    cfg.pdoaMode = DWT_PDOA_M0;

    if (dwt_configure(&cfg) != DWT_SUCCESS) {
        return -2;
    }

    dwt_txconfig_t txcfg;
    txcfg.PGdly = 0x34;
    txcfg.power = 0x0F1F1F1FUL;
    txcfg.PGcount = 0;
    dwt_configuretxrf(&txcfg);

    /* 4) 完成基本配置后切换到高速 SPI（例如 ~18MHz） */
    port_set_dw_ic_spi_fastrate();

    /* 启用 DW 芯片内部 LED（GPIO0~3 -> RXOK/SFD/RX/TX），并在初始化后闪烁一次 */
    dwt_setleds(DWT_LEDS_ENABLE | DWT_LEDS_INIT_BLINK);

    // dwt_setcallbacks(on_tx_done, on_rx_ok, on_rx_to, on_rx_err, NULL, NULL);

    // 使能常用中断：RXOK/RXERR/RX 超时/TX 完成/ARFE 等
    uint32_t mask_lo = DWT_INT_RFCG | DWT_INT_RFCE | DWT_INT_RPHE |
                       DWT_INT_RFSL | DWT_INT_RXOVRR | DWT_INT_RXPTO |
                       DWT_INT_SFDT | DWT_INT_TFRS | DWT_INT_CPERR |
                       DWT_INT_ARFE | DWT_INT_RFTO;
    dwt_setinterrupt(mask_lo, 0, DWT_ENABLE_INT);

    if (dwt_rxenable(DWT_START_RX_IMMEDIATE) != DWT_SUCCESS) {
        return -3;
    }

    return 0;
}

/* ======== 平台适配：延时函数 ======== */
void Sleep(unsigned int time_ms) {
    HAL_Delay(time_ms);
}

void deca_sleep(unsigned int time_ms) {
    Sleep(time_ms);
}

/* 微秒级延时：使用 DWT CYCCNT */
void deca_usleep(unsigned long time_us) {
    static uint8_t dwt_inited = 0;
    if (!dwt_inited) {
        /* 允许 DWT 计数器 */
        CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
        DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
        dwt_inited = 1;
    }
    uint32_t cycles = (uint32_t) ((SystemCoreClock / 1000000UL) * time_us);
    uint32_t start = DWT->CYCCNT;
    while ((uint32_t) (DWT->CYCCNT - start) < cycles) {
        __NOP();
    }
}

/* ======== 平台适配：中断开关 ======== */
void disable_deca_irq(void) {
    NVIC_DisableIRQ(DW3000_IRQ_EXTI_IRQn);
}

void enable_deca_irq(void) {
    NVIC_EnableIRQ(DW3000_IRQ_EXTI_IRQn);
}

/* ======== 平台适配：SPI 速率切换 ======== */
extern SPI_HandleTypeDef hspi1;

static void spi_apply_prescaler(uint32_t prescaler) {
    /* 片选拉高，避免切速过程中误触发 */
    HAL_GPIO_WritePin(DW3000_CS_GPIO_Port, DW3000_CS_Pin, GPIO_PIN_SET);

    HAL_SPI_DeInit(&hspi1);
    hspi1.Init.BaudRatePrescaler = prescaler;
    HAL_SPI_Init(&hspi1);
}

/* 直接设置指定分频（传入 HAL 的 SPI_BAUDRATEPRESCALER_x 宏） */
void SPI_ConfigFastRate(uint16_t scalingfactor) {
    spi_apply_prescaler((uint32_t) scalingfactor);
}

/* 低速（初始化/复位/睡眠阶段，<3MHz） */
void port_set_dw_ic_spi_slowrate(void) {
    /* APB2 72MHz -> 分频32 ≈ 2.25MHz */
    spi_apply_prescaler(SPI_BAUDRATEPRESCALER_32);
}

/* 高速（正常通讯，如 18MHz） */
void port_set_dw_ic_spi_fastrate(void) {
    /* APB2 72MHz -> 分频4 */
    spi_apply_prescaler(SPI_BAUDRATEPRESCALER_4);
}
