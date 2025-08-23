// Core/Src/UWB/deca_spi_port.c
#include "uwb.h"
#include "main.h"

extern SPI_HandleTypeDef hspi1;

static inline int spi_tx(const uint8_t *buf, uint16_t len) {
    if (len == 0) return 0;
    return (HAL_OK == HAL_SPI_Transmit(&hspi1, (uint8_t*)buf, len, HAL_MAX_DELAY)) ? 0 : -1;
}

static inline int spi_trx(const uint8_t *tx, uint8_t *rx, uint16_t len) {
    if (len == 0) return 0;
    // 当 tx 为 NULL 时，发送 0xFF 作为 dummy
    if (tx) {
        return (HAL_OK == HAL_SPI_TransmitReceive(&hspi1, (uint8_t*)tx, rx, len, HAL_MAX_DELAY)) ? 0 : -1;
    } else {
        // 逐字节 dummy 发送
        for (uint16_t i = 0; i < len; ++i) {
            uint8_t d = 0xFF;
            if (HAL_OK != HAL_SPI_TransmitReceive(&hspi1, &d, &rx[i], 1, HAL_MAX_DELAY)) {
                return -1;
            }
        }
        return 0;
    }
}

// 写：先发 header，再发 body
int writetospi_serial(uint16_t headerLength,
                      const uint8_t *headerBuffer,
                      uint16_t bodylength,
                      const uint8_t *bodyBuffer)
{
    port_SPIx_clear_chip_select();
    int rc = 0;
    if (rc == 0) rc = spi_tx(headerBuffer, headerLength);
    if (rc == 0) rc = spi_tx(bodyBuffer, bodylength);
    port_SPIx_set_chip_select();
    return (rc == 0) ? 0 : -1;
}

// 读：先发 header，再读 body（dummy 填充）
int readfromspi_serial(uint16_t headerLength,
                       uint8_t *headerBuffer,
                       uint16_t readlength,
                       uint8_t *readBuffer)
{
    port_SPIx_clear_chip_select();
    int rc = 0;
    if (rc == 0) rc = spi_tx(headerBuffer, headerLength);
    if (rc == 0) rc = spi_trx(NULL, readBuffer, readlength);
    port_SPIx_set_chip_select();
    return (rc == 0) ? 0 : -1;
}
