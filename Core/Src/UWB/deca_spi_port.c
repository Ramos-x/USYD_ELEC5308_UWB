#include "uwb.h"
#include "stm32f1xx_hal.h"

extern SPI_HandleTypeDef hspi1;

// 发送缓冲区
static inline int spi_tx(const uint8_t *buf, uint16_t len) {
    if (len == 0) return 0;
    return (HAL_OK == HAL_SPI_Transmit(&hspi1, (uint8_t *)buf, len, HAL_MAX_DELAY)) ? 0 : -1;
}

// 接收缓冲区（通过时钟采样读取）
static inline int spi_rx(uint8_t *buf, uint16_t len) {
    if (len == 0) return 0;
    return (HAL_OK == HAL_SPI_Receive(&hspi1, buf, len, HAL_MAX_DELAY)) ? 0 : -1;
}

/**
 * 写 SPI：先写 header，再写 body
 */
int writetospi_serial(uint16_t headerLength,
                      const uint8_t *headerBuffer,
                      uint16_t bodylength,
                      const uint8_t *bodyBuffer)
{
    port_SPIx_clear_chip_select();
    int rc = 0;
    if (rc == 0 && headerLength) rc = spi_tx(headerBuffer, headerLength);
    if (rc == 0 && bodylength)   rc = spi_tx(bodyBuffer, bodylength);
    port_SPIx_set_chip_select();
    return (rc == 0) ? 0 : -1;
}

/**
 * 读 SPI：先写 header，再读 body
 */
int readfromspi_serial(uint16_t headerLength,
                       uint8_t *headerBuffer,
                       uint16_t readlength,
                       uint8_t *readBuffer)
{
    port_SPIx_clear_chip_select();
    int rc = 0;
    if (rc == 0 && headerLength) rc = spi_tx(headerBuffer, headerLength);
    if (rc == 0 && readlength)   rc = spi_rx(readBuffer, readlength);
    port_SPIx_set_chip_select();
    return (rc == 0) ? 0 : -1;
}
