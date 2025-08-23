/*! ----------------------------------------------------------------------------
 * @file	deca_mutex.c
 * @brief	IRQ interface / mutex implementation
 *
 * @attention
 *
 * Copyright 2013 (c) DecaWave Ltd, Dublin, Ireland.
 *
 * All rights reserved.
 *
 */

#include "uwb.h"

// ---------------------------------------------------------------------------
//
// NB: The purpose of the deca_mutex.c file is to provide for microprocessor interrupt enable/disable, this is used for
//     controlling mutual exclusion from critical sections in the code where interrupts and background
//     processing may interact.  The code using this is kept to a minimum and the disabling time is also
//     kept to a minimum, so blanket interrupt disable may be the easiest way to provide this.  But at a
//     minimum those interrupts coming from the Decawave device should be disabled/re-enabled by this activity.
//
//     In porting this to a particular microprocessor, the implementer may choose to use #defines here
//     to map these calls transparently to the target system.  Alternatively the appropriate code may
//     be embedded in the functions provided in the deca_irq.c file.
//
// ---------------------------------------------------------------------------

typedef int decaIrqStatus_t ; // Type for remembering IRQ status

/*! ------------------------------------------------------------------------------------------------------------------
 * Function: decamutexon()
 *
 * Description: Disable DW3000外部中断，进入临界区；返回进入前的中断使能状态
 *
 * returns: 进入前中断是否使能（非0为已使能）
 */
decaIrqStatus_t decamutexon(void)
{
    decaIrqStatus_t s = (decaIrqStatus_t)port_GetEXT_IRQStatus();
    if (s) {
        port_DisableEXT_IRQ();
    }
    return s;
}

/**
 * @brief  退出临界区：按进入时的中断状态恢复外部中断
 * @param  s: 进入临界区 decamutexon() 返回的状态值（非零表示进入前中断已开启）
 */
void decamutexoff(decaIrqStatus_t s)
{
    if (s) {
        port_EnableEXT_IRQ();
    }
}
