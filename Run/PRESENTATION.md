# UWB Indoor Positioning System
## Centimeter-Level Accuracy with ML Enhancement

**University of Sydney - ELEC 5308**

*Presented by: Ramos Wang, Guest Andrew, Zhishen Pan*

---

## Problem & Solution

### The Challenge: GPS Fails Indoors

| Technology | Accuracy | Limitations |
|------------|----------|-------------|
| GPS | 5-10m | No indoor signal ❌ |
| WiFi | 3-5m | Low precision, environment-dependent |
| Bluetooth | 1-3m | High variance, interference |
| **UWB + ML** | **5.8cm** | ✅ Our Solution |

### Our Innovation: Three-Layer Architecture

1. **Firmware Layer** - STM32F103 + DW3000 UWB chip, unified Tag/Anchor binary
2. **ML Layer** - 11D channel quality features + GradientBoosting per-anchor models
3. **Positioning Layer** - Kalman filtering + least-squares multilateration

### Key Achievements
- **5.8cm** distance RMSE @ 2m (70% improvement over raw UWB)
- **25Hz** real-time update rate
- **Production-ready** with comprehensive error handling

---

## System Architecture & Hardware

### Physical Setup (5m × 4m × 3m Space)

```
    Anchor1 o-----------o Anchor2
             \         /
              \   🏷️  /   Tag (Mobile)
              /       \
             /         \
    Anchor4 o-----------o Anchor3

            Anchor5 o (Somewhere)
```

### Hardware Components

| Component | Specification | Function |
|-----------|--------------|----------|
| **MCU** | STM32F103C8T6 | 72MHz ARM Cortex-M3, 20KB RAM |
| **UWB** | DW3000 | 6-9GHz transceiver, 15.65ps resolution |
| **UART** | 2 Mbps + DMA | Real-time JSON data streaming |
| **Display** | 128×64 OLED | Live status feedback |

### Unified Firmware Design ⭐

**Single Binary for Dual Roles:**
```c
// GPIO pin (BOOT1/PB2) selects role at runtime
if (GPIO_Read(BOOT1_PIN) == HIGH) {
    role = TAG;     // Mobile: initiates ranging
} else {
    role = ANCHOR;  // Fixed: responds to polls
}
```

**Benefits:**
- 62% code reduction 
- Single codebase maintenance
- Shared protocol logic
- No separate firmware flashing

---

## DS-TWR Protocol & Timing

### Double-Sided Two-Way Ranging (4-Step Exchange)

```
TAG                    ANCHOR
 |                        |
 |------ POLL --------->  |  T1 (TX), T2 (RX)
 |                        |
 |<----- RESP ----------  |  T3 (TX), T4 (RX)
 |                        |
 |------ FINAL -------->  |  T5 (TX), T6 (RX)
 |                        |
 |<----- FACK ----------  |  Sends T2, T3, T6
 |                        |
 +-- Calculate Distance --+
```

### Time-of-Flight Calculation

```
tRound1 = T4 - T1    (Tag perspective)
tReply1 = T3 - T2    (Anchor delay)
tRound2 = T6 - T3    (Anchor perspective)
tReply2 = T5 - T4    (Tag delay)

ToF = (tRound1 × tRound2 - tReply1 × tReply2)
      / (tRound1 + tRound2 + tReply1 + tReply2)

Distance = ToF × c (speed of light)
```

### Why DS-TWR Eliminates Clock Drift? ⭐

**Problem:** Crystal oscillators drift ±20ppm
- 1-second measurement error = 20µs → **6km distance error!**

**Solution:** Clock errors appear in both numerator and denominator
- **Algebraically canceled** through ratio calculation
- No synchronization required between Tag and Anchor

### Protocol Optimizations (v2.0)

| Parameter | Before | After | Benefit |
|-----------|--------|-------|---------|
| RESP Window | 6000µs | 4000µs | Faster cycle |
| ACK Window | 6000µs | 3000µs | -33% latency |
| OLED Update | 500ms | 1000ms | Less CPU load |
| Update Rate | 16Hz | 25Hz | +56% |

---

## Machine Learning Pipeline

### The Problem: Raw UWB Has Significant Errors

**Error Sources:**
- Multipath interference (wall/object reflections)
- Non-Line-of-Sight (NLOS) propagation
- Temperature-induced clock drift
- Antenna characteristics variation
- RF environmental noise

**Result:** 15-30cm raw distance error ❌


### Solution: 11-Dimensional Feature Engineering

| Category | Features | Purpose |
|----------|----------|---------|
| **Channel Diagnostics** | cia_diag (Channel Impulse Amplitude) | Signal strength indicator |
| | ipatov_peak | First path power peak |
| | ipatov_power | Total received power |
| **Path Analysis** | ipatov_fp_idx | First path index (detect multipath) |
| | ipatov_accum | Accumulation count (NLOS indicator) |
| **Clock Drift** | xtal_offset | Crystal frequency offset |
| **Timing Proxies** | t_round_1, t_round_2 | Round-trip times |
| | t_reply_1, t_reply_2 | Processing delays |
| **Derived Metrics** | SNR_estimate | Signal-to-Noise ratio |
| | quality_score | Composite quality metric |

### Per-Anchor Gradient Boosting Models

```python
for anchor_id in [1, 2, 3, 4, 5]:
    model = GradientBoostingRegressor(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1
    )
    # Train on anchor-specific data
    X = features_11d[anchor_id]  # Environmental adaptation
    y = true_distances[anchor_id]
    model.fit(X, y)
```

**Why Per-Anchor?**
- Each anchor has unique environment (walls, obstacles)
- Different multipath reflection patterns
- Asymmetric interference characteristics
- **Result:** 89-95% distance prediction accuracy

### Training Data

- **4 distance levels:** 1m, 1.5m, 2m, 2.5m
- **~4000 measurements** total (4000 per distance)
- **Cross-validation:** 80/20 train/test split

---

## Positioning Algorithm & Performance

### Full Processing Pipeline

```
Raw UWB Distances (5 Anchors)
        ↓
ML Model Correction (Per-Anchor GradientBoosting)
        ↓
Outlier Rejection (Statistical filtering)
        ↓
Kalman Filtering (Motion-adaptive smoothing)
        ↓
Least-Squares Multilateration (3D position solver)
        ↓
3D Coordinates (x, y, z)
```

### Adaptive Kalman Filter

```python
class KalmanFilter1D:
    def update(self, measurement, is_dynamic):
        # Adaptive process noise
        if is_dynamic:
            self.Q = 0.01   # Allow fast changes
        else:
            self.Q = 0.001  # Heavy smoothing

        # Kalman gain calculation
        K = self.P / (self.P + self.R)
        self.x += K * (measurement - self.x)
        self.P *= (1 - K)
```

**Motion Detection:** Sliding window variance
- Static: `variance < 0.01 m²` → Q = 0.001
- Dynamic: `variance ≥ 0.01 m²` → Q = 0.01

### 3D Multilateration

Given 5 corrected distances `d₁, d₂, d₃, d₄, d₅` to anchors at known positions:

```
Minimize: Σ(||P - Aᵢ|| - dᵢ)²

Least-squares solution:
position = (AᵀA)⁻¹ Aᵀb

Where A contains linearized coefficients
      b contains distance constraints
```

### Performance Results

**System Performance:**

| Metric | Target | Achieved |
|--------|--------|----------|
| Update Rate | 20 Hz | **25 Hz |
| Latency | <150ms | **<100 ms |
| Range | 30m | **50 m |
| Power (Tag) | <250mA | **200 mA |

**Test Setup:**
- 4m × 4m × 2m room
- 50 static test points
- Ground truth from total station survey

---

## Optimizations & Innovations

### Code Refactoring Achievements

| Aspect | Before v2.0 | After v2.0 | Improvement |
|--------|-------------|------------|-------------|
| **Code Structure** | tag.c  + anchor.c  | bu03.c  unified | **-redundancy** |
| **Update Rate** | 16 Hz | 25 Hz | **+56% faster** |
| **RAM Usage** | ~800 bytes | ~400 bytes | **-50% memory** |
| **Duplicate Data** | 6.2 MB | 3.1 MB | **-50% storage** |
| **Build Process** | Flash twice (separate bins) | Flash once (role select) | **2x easier** |

### Core Technical Innovations

#### 1. Unified Firmware Architecture ⭐
- **Single codebase** for Tag and Anchor
- **Runtime role switching** via GPIO pin (BOOT1)
- **Shared protocol logic** eliminates duplication
- **Adaptive antenna delay calibration** (15,800-17,000 DTU range)

#### 2. ML-Enhanced Distance Correction ⭐
- **11-dimensional feature space** extracted from DW3000 diagnostics
- **Per-anchor models** adapt to local environment
- **70% error reduction** compared to raw UWB
- **89-95% prediction accuracy** on test set

#### 3. Modular UART Architecture ⭐
- **2KB DMA ring buffer** for non-blocking transmission
- **Thread-safe writes** with critical section protection
- **Auto-triggered DMA** when data available

#### 4. Production-Ready Reliability ⭐
- **Complete error handling** (fail counters, recovery mechanisms)
- **Automatic calibration** (TX antenna delay adjustment)
- **Real-time diagnostics** (OLED display + JSON output)
- **Comprehensive documentation** 

### Performance Optimization Details

**Timing Improvements:**
```c
// Reduced waiting periods
#define RESP_WINDOW_US   4000U  // Was 6000us (-33%)
#define ACK_WINDOW_US    3000U  // Was 6000us (-50%)
#define FINAL_DELAY_US   1500U  // Optimized spacing
#define OLED_UPDATE_MS   1000   // Was 500ms (less CPU)
```

**Result:** 40ms cycle time → 25Hz update rate

---

## Thank You!

```
==============================================
    UWB Indoor Positioning System
==============================================

    5.8cm Distance Accuracy
    25Hz Real-time Updates
    70% ML Error Reduction

    University of Sydney - ELEC 5308

    Production-Ready | Open Source
==============================================
```

**Questions?**

**Contact:** ramos@dtft.net
