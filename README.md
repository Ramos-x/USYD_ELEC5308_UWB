# UWB Indoor Positioning System

A high-precision indoor positioning system based on Ultra-Wideband (UWB) technology with machine learning-enhanced distance correction and real-time 3D localization capabilities.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Hardware Components](#hardware-components)
- [Software Components](#software-components)
- [Branch Information](#branch-information)
- [Getting Started](#getting-started)
- [Directory Structure](#directory-structure)
- [Usage](#usage)

## Overview

This project implements a complete UWB-based indoor positioning system that combines embedded firmware for STM32F103 microcontrollers with Python-based machine learning algorithms to achieve centimeter-level positioning accuracy. The system utilizes Double-Sided Two-Way Ranging (DS-TWR) protocol and channel quality parameters to correct distance measurements and perform 3D multilateration.

## Key Features

### Hardware
- **STM32F103 Firmware**: Real-time UWB transceiver control with DW3000 chipset
- **DS-TWR Protocol**: Double-sided two-way ranging for accurate time-of-flight measurements
- **Channel Quality Diagnostics**: Extraction of 11+ channel parameters for ML-based correction
- **OLED Display Support**: Real-time status visualization on hardware
- **ESP32 JSON Relay**: Wireless data transmission to processing units

### Software
- **Machine Learning Distance Correction**:
  - Gradient Boosting and Random Forest models
  - Per-anchor calibration
  - 30-60% improvement in distance accuracy
- **Adaptive Kalman Filtering**:
  - Automatic motion detection (static/dynamic)
  - Self-adjusting noise parameters
- **Real-time 3D Positioning**:
  - Multi-anchor trilateration
  - Sub-meter accuracy in typical indoor environments
- **Visualization Tools**:
  - Live 2D trajectory plotting
  - Distance monitoring per anchor
  - Performance analytics

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    UWB Tag (STM32F103)                      │
│  - DW3000 UWB Transceiver                                   │
│  - DS-TWR Protocol Implementation                           │
│  - Channel Quality Diagnostics (rxq)                        │
│  - JSON Output via UART                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ UART/WiFi (ESP32)
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Python Processing System                       │
│                                                              │
│  1. Data Acquisition                                        │
│     └─ Parse JSON, extract timestamps & channel quality     │
│                                                              │
│  2. Feature Extraction (11 features)                        │
│     ├─ Raw: peak, power, fp_index, acc_count, xtal_offset  │
│     └─ Derived: SNR, normalized power, FP quality, etc.     │
│                                                              │
│  3. ML Distance Correction (Gradient Boosting)              │
│     └─ Per-anchor trained models                            │
│                                                              │
│  4. Motion Detection                                        │
│     └─ Sliding window variance analysis                     │
│                                                              │
│  5. Adaptive Kalman Filtering                               │
│     ├─ Static: Q=0.001, R=0.05                              │
│     └─ Dynamic: Q=0.05, R=0.15                              │
│                                                              │
│  6. 3D Multilateration                                      │
│     └─ Least-squares position estimation                    │
│                                                              │
│  7. Visualization & Logging                                 │
└─────────────────────────────────────────────────────────────┘
```

## Hardware Components

### Required Hardware
- **UWB Modules**: DW3000-based UWB transceivers (minimum 4 anchors + 1 tag)
- **Microcontroller**: STM32F103 series (BluePill or equivalent)
- **Display** (optional): I2C OLED display for status monitoring
- **Data Relay** (optional): ESP32 for WiFi connectivity

### Anchor Configuration
Optimal setup requires:
- 4-5 anchors positioned to form a 3D geometric layout
- Minimum 4 anchors for 3D positioning
- Non-coplanar arrangement for Z-axis accuracy
- Measured and calibrated coordinates

## Software Components

### Firmware (STM32)
- **Language**: C (C11 standard)
- **Build System**: CMake
- **Key Files**:
  - `Core/Src/UWB/bu03.c`: Main UWB protocol implementation
  - `Core/Src/UWB/deca_device.c`: DW3000 driver
  - `Core/Src/UWB/uwb_frames.c`: Frame handling
  - `Core/Src/app.c`: Application logic

### Python Software
- **Requirements**: Python 3.7+
- **Dependencies**:
  - `numpy`, `pandas`: Data processing
  - `scikit-learn`: Machine learning models
  - `matplotlib`: Visualization
  - `pyserial`: Serial communication

- **Key Modules**:
  - `Run/Training/enhanced_positioning_model.py`: Core positioning algorithms
  - `Run/Training/train_enhanced_model.py`: Model training script
  - `Run/Training/realtime_positioning.py`: Live positioning application
  - `Run/Training/visualize_positioning.py`: Visualization tools

## Branch Information

This repository maintains two main branches:

### Master Branch
- **Purpose**: Stable release branch
- **Status**: Production-ready code
- **Updates**: Tested features and bug fixes only
- **Use Case**: Deployment and reliable operation

### Beta Branch
- **Purpose**: Development and testing branch
- **Status**: Latest features and experimental code
- **Updates**: Frequent commits with new features
- **Use Case**: Testing, development, and feature exploration

**Recommendation**:
- Use **Master** for production deployments
- Use **Beta** for development and testing new features
- Pull requests should be made to **Beta** branch first

## Getting Started

### 1. Firmware Setup

#### Prerequisites
- STM32CubeIDE or CMake + ARM toolchain
- ST-Link programmer

#### Build Instructions
```bash
# Clone the repository
git clone <repository-url>
cd USYD_ELEC5308_UWB

# Build using CMake
mkdir build && cd build
cmake ..
make

# Flash to STM32
# Use STM32CubeProgrammer or your preferred flashing tool
```

#### Configure Tag/Anchor Mode
Edit `Core/Src/UWB/bu03.c` to set device role and parameters.

### 2. Python Environment Setup

```bash
# Install Python dependencies
pip install numpy pandas scikit-learn matplotlib pyserial

# Verify installation
cd Run/Training
python test_model.py
```

### 3. Data Collection for Training

Collect training data at known distances:

```bash
# Place tag at known distances from anchors (e.g., 0.5m, 1m, 1.5m, 2m, etc.)
# Run data collection tool
python Run/tool/collect_uwb.py

# Convert to training format
python Run/tool/json2csv.py
```

### 4. Train ML Models

```bash
cd Run/Training
python train_enhanced_model.py
```

**Expected Output**:
- `uwb_distance_correction_model.pkl`: Trained model file
- `correction_comparison.png`: Performance visualization
- Training metrics showing 30-60% accuracy improvement

### 5. Configure Anchor Positions

Edit `realtime_positioning.py` with your measured anchor coordinates:

```python
anchor_positions = {
    1: [0.0, 0.0, 1.0],      # [X, Y, Z] in meters
    2: [3.0, 0.0, 1.0],
    3: [3.0, 3.0, 1.0],
    4: [0.0, 3.0, 1.0],
    5: [1.5, 1.5, 2.5],      # Elevated for Z-axis accuracy
}
```

### 6. Run Real-time Positioning

```bash
python Run/Training/realtime_positioning.py
```

Select the COM port and optionally enable visualization for live tracking.

## Directory Structure

```
USYD_ELEC5308_UWB/
├── Core/                           # STM32 firmware source code
│   ├── Src/
│   │   ├── UWB/                    # UWB protocol implementation
│   │   │   ├── bu03.c              # Main UWB logic & DS-TWR
│   │   │   ├── deca_device.c       # DW3000 hardware driver
│   │   │   ├── uwb_frames.c        # Frame construction/parsing
│   │   │   ├── calibration.c       # Calibration routines
│   │   │   └── discovery.c         # Network discovery
│   │   ├── OLED/                   # Display driver
│   │   ├── app.c                   # Application entry point
│   │   └── main.c                  # System initialization
│   └── Inc/                        # Header files
│
├── Drivers/                        # STM32 HAL and peripheral drivers
│
├── Run/                            # Python positioning system
│   ├── Training/                   # ML training and positioning
│   │   ├── enhanced_positioning_model.py
│   │   ├── train_enhanced_model.py
│   │   ├── realtime_positioning.py
│   │   └── visualize_positioning.py
│   ├── tool/                       # Utility scripts
│   │   ├── collect_uwb.py          # Data collection
│   │   ├── json2csv.py             # Format conversion
│   │   └── train_distance_model.py
│   └── *.py                        # Legacy/alternative implementations
│
├── ESP32_JSON_Relay/               # ESP32 WiFi relay (optional)
│   └── test_receive_TCP/
│
├── Doc/                            # Documentation and datasheets
│
├── CMakeLists.txt                  # CMake build configuration
├── STM32F103XX_FLASH.ld            # Linker script
├── UWB.ioc                         # STM32CubeMX project file
└── README.md                       # This file
```

## Usage

### Real-time Positioning Output

```
[0042] Position: X= 1.234m Y= 2.567m Z= 1.123m | Static | Velocity: 0.015m/s | Anchors: 5
[0043] Position: X= 1.235m Y= 2.568m Z= 1.124m | Static | Velocity: 0.012m/s | Anchors: 5
```

### JSON Output Format (from Firmware)

```json
{
  "role": "tag",
  "anchors": [
    {
      "aid": 3,
      "ex": {
        "tx1": "1234567890",
        "rx1": "1234567891",
        "tx2": "1234567892",
        "rx2": "1234567893",
        "tx3r": "1234567894",
        "rx3": "1234567895",
        "complete": 1
      },
      "qual": {
        "cia": 123456,
        "ipatov": {
          "peak": 1551905179,
          "pwr": 12,
          "fp_idx": 47246,
          "acc": 49
        },
        "xo": 10
      }
    }
  ]
}
```

## Troubleshooting

### Issue: No position calculated
- **Cause**: Insufficient anchors (< 4) or incomplete measurements
- **Solution**: Verify anchor connectivity and `complete` flag in JSON output

### Issue: High positioning jitter
- **Cause**: Low signal quality or multipath interference
- **Solution**: Adjust Kalman filter parameters in `enhanced_positioning_model.py`

### Issue: Z-axis inaccuracy
- **Cause**: All anchors at same height (poor GDOP)
- **Solution**: Place at least one anchor at different elevation (>1m difference)


## Acknowledgments

- **Hardware**: DW3000 UWB transceiver
- **Framework**: STM32 HAL, scikit-learn
- **Protocol**: IEEE 802.15.4a UWB standard

---

**Project Course**: ELEC5308 - University of Sydney
**Technology**: UWB, STM32, Machine Learning, Indoor Positioning
**Last Updated**: 2025-11