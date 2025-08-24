/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f1xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define PB13_Pin GPIO_PIN_13
#define PB13_GPIO_Port GPIOC
#define DW_RSTN_Pin GPIO_PIN_0
#define DW_RSTN_GPIO_Port GPIOA
#define LED_RUN_Pin GPIO_PIN_1
#define LED_RUN_GPIO_Port GPIOA
#define PA2_Pin GPIO_PIN_2
#define PA2_GPIO_Port GPIOA
#define PA3_Pin GPIO_PIN_3
#define PA3_GPIO_Port GPIOA
#define SPI1_CSN_Pin GPIO_PIN_4
#define SPI1_CSN_GPIO_Port GPIOA
#define DW_WAKEUP_Pin GPIO_PIN_0
#define DW_WAKEUP_GPIO_Port GPIOB
#define DW_SYNC_Pin GPIO_PIN_1
#define DW_SYNC_GPIO_Port GPIOB
#define BOOT1_Pin GPIO_PIN_2
#define BOOT1_GPIO_Port GPIOB
#define PB12_Pin GPIO_PIN_12
#define PB12_GPIO_Port GPIOB
#define PB13B13_Pin GPIO_PIN_13
#define PB13B13_GPIO_Port GPIOB
#define PB14_Pin GPIO_PIN_14
#define PB14_GPIO_Port GPIOB
#define PB15_Pin GPIO_PIN_15
#define PB15_GPIO_Port GPIOB
#define EXTON_Pin GPIO_PIN_8
#define EXTON_GPIO_Port GPIOA
#define SWDIO_Pin GPIO_PIN_13
#define SWDIO_GPIO_Port GPIOA
#define SWCLK_Pin GPIO_PIN_14
#define SWCLK_GPIO_Port GPIOA
#define PA15_Pin GPIO_PIN_15
#define PA15_GPIO_Port GPIOA
#define PB3_Pin GPIO_PIN_3
#define PB3_GPIO_Port GPIOB
#define PB4_Pin GPIO_PIN_4
#define PB4_GPIO_Port GPIOB
#define DW_IRQ_Pin GPIO_PIN_5
#define DW_IRQ_GPIO_Port GPIOB
#define PB8_Pin GPIO_PIN_8
#define PB8_GPIO_Port GPIOB
#define PB9_Pin GPIO_PIN_9
#define PB9_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */
/* UWB的 LEDTX/LEDRX/LEDSFD/LEDRXOK 由 BU03(DW3000) 芯片 GPIO3/2/1/0 内部驱动，此处无需STM32侧映射 */
/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
