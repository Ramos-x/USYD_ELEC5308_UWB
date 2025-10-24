# UWB增强型定位系统 - Training目录

## 目录结构

```
Training/
├── enhanced_positioning_model.py    # 核心模型库（类定义）
├── train_enhanced_model.py          # 模型训练脚本
├── realtime_positioning.py          # 实时定位应用
├── test_model.py                     # 功能测试脚本
├── out_1m.csv                        # 1米距离训练数据
├── out_2m.csv                        # 2米距离训练数据
├── README_enhanced_model.md          # 详细英文文档
├── 使用说明.md                       # 中文快速指南
└── README.md                         # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install numpy pandas scikit-learn matplotlib pyserial
```

### 2. 测试功能

```bash
python test_model.py
```

### 3. 训练模型

```bash
python train_enhanced_model.py
```

这会生成：
- `uwb_distance_correction_model.pkl` - 训练好的模型
- `correction_comparison.png` - 校正效果对比图
- `error_distribution.png` - 误差分布图

### 4. 实时定位

```bash
python realtime_positioning.py
```

## 文件说明

### enhanced_positioning_model.py
核心模型库，包含：
- `ChannelQualityFeatureExtractor` - 特征提取器
- `DistanceCorrectionModel` - 距离校正模型
- `MotionDetector` - 运动检测器
- `KalmanFilter1D` - 卡尔曼滤波器
- `EnhancedPositioningSystem` - 完整定位系统

### train_enhanced_model.py
模型训练脚本：
- 加载out_1m.csv和out_2m.csv
- 为每个anchor训练独立模型
- 生成可视化对比图
- 保存训练好的模型

### realtime_positioning.py
实时定位应用：
- 自动检测串口
- 解析JSON格式的UWB数据
- 应用距离校正和滤波
- 计算3D坐标
- 可选的实时可视化

### test_model.py
功能测试脚本，验证：
- 特征提取器
- 运动检测器
- 卡尔曼滤波器
- 多边定位算法

### 训练数据
- `out_1m.csv` - 各anchor在1米距离的测量数据
- `out_2m.csv` - 各anchor在2米距离的测量数据

格式：每个anchor有6列数据
- `a{N}_m` - 测量距离(米)
- `a{N}_peak` - 峰值功率
- `a{N}_pwr` - 总功率
- `a{N}_fp_idx` - 首径索引
- `a{N}_acc` - 累积计数
- `a{N}_xo` - 晶振偏移

## 核心算法

### 1. 基于信道质量的ML距离校正

从DW3000的诊断信息中提取11个特征：
- 5个原始特征: peak, pwr, fp_idx, acc, xo
- 6个派生特征: SNR估算, 归一化功率, 首径质量等

使用Gradient Boosting训练模型，预测距离误差并校正。

### 2. 自适应场景识别

基于滑动窗口方差分析：
- 静态场景: 方差 < 阈值² → 高精度滤波
- 动态场景: 方差 > 阈值² → 快速响应

### 3. 卡尔曼滤波

自适应调整参数：
- 静态: Q=0.001, R=0.05 (平滑)
- 动态: Q=0.05, R=0.15 (响应)

### 4. 多边定位

最小二乘法求解3D坐标，需要4个或以上anchor。

## 性能指标

预期改善：
- MAE降低: 30-60%
- 静态定位精度: 5-10cm
- 动态定位精度: 10-20cm

## 扩展数据采集

建议采集更多距离点以提升模型泛化能力：

```bash
# 在固件中设置不同距离，重复采集
# 0.5m, 1.0m, 1.5m, 2.0m, 2.5m, 3.0m, 4.0m, 5.0m
# 每个距离500-1000个样本
```

然后在train_enhanced_model.py中添加：

```python
csv_files = [
    'out_0.5m.csv',
    'out_1m.csv',
    'out_1.5m.csv',
    'out_2m.csv',
    'out_2.5m.csv',
    'out_3m.csv',
    'out_4m.csv',
    'out_5m.csv'
]

true_distances = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
```

## 更多信息

- 详细文档: `README_enhanced_model.md` (英文)
- 快速指南: `使用说明.md` (中文)
- 固件代码: `../Core/Src/UWB/bu03.c` (信道质量采集)

## 技术支持

如遇问题，请检查：
1. Python版本 >= 3.7
2. 所有依赖已安装
3. 串口波特率设置为2000000
4. 锚点坐标配置正确
