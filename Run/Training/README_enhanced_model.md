# 增强型UWB定位系统

基于信道质量参数的距离校正和动静态场景识别的UWB室内定位系统

## 功能特性

### 1. 基于机器学习的距离校正
- 利用DW3000芯片的信道质量参数（CIR诊断信息）
- 提取11个特征：
  - 原始参数：peak（峰值）、pwr（功率）、fp_idx（首径索引）、acc（累积计数）、xo（晶振偏移）
  - 派生特征：SNR估算、归一化功率、峰值功率比、复合质量指标等
- 支持两种机器学习算法：
  - Gradient Boosting（梯度提升，默认）
  - Random Forest（随机森林）
- 为每个anchor训练独立模型，适应不同环境特性

### 2. 动态/静态场景自动识别
- 基于滑动窗口的方差分析
- 自动检测tag是否在运动
- 速度估算功能

### 3. 卡尔曼滤波器
- 一维卡尔曼滤波平滑距离测量
- 根据场景自适应调整参数：
  - 静态场景：低过程噪声，高测量置信度
  - 动态场景：高过程噪声，快速响应

### 4. 多边定位算法
- 最小二乘法求解3D坐标
- 支持4个或以上anchor

### 5. 实时可视化
- 2D轨迹图
- 各anchor距离变化曲线
- 运动状态指示

## 文件说明

```
Run/tool/
├── enhanced_positioning_model.py    # 核心模型代码（类库）
├── train_enhanced_model.py          # 模型训练脚本
├── realtime_positioning.py          # 实时定位应用
├── out_1m.csv                        # 1米距离训练数据
├── out_2m.csv                        # 2米距离训练数据
├── uwb_distance_correction_model.pkl # 训练好的模型（生成）
└── README_enhanced_model.md          # 本文档
```

## 使用流程

### 步骤1: 准备环境

安装依赖库：
```bash
pip install numpy pandas scikit-learn matplotlib pyserial
```

### 步骤2: 训练模型

运行训练脚本：
```bash
cd Run/tool
python train_enhanced_model.py
```

**输出：**
- `uwb_distance_correction_model.pkl` - 训练好的模型
- `correction_comparison.png` - 校正效果对比图
- `error_distribution.png` - 误差分布图

**预期效果：**
- MAE（平均绝对误差）降低30%-60%
- 控制台输出每个anchor的详细训练结果

### 步骤3: 配置锚点坐标

编辑 `realtime_positioning.py`，修改 `anchor_positions` 字典：

```python
anchor_positions = {
    1: [0.0, 0.0, 1.0],      # Anchor 1的[x, y, z]坐标
    2: [3.0, 0.0, 1.0],      # Anchor 2
    3: [3.0, 3.0, 1.0],      # Anchor 3
    4: [0.0, 3.0, 1.0],      # Anchor 4
    5: [1.5, 1.5, 2.5],      # Anchor 5
}
```

**注意：** 这些坐标必须通过实际测量标定！

### 步骤4: 实时定位

连接UWB设备到USB串口，然后运行：
```bash
python realtime_positioning.py
```

程序会：
1. 自动检测可用串口
2. 加载训练好的模型
3. 实时读取并解析JSON数据
4. 应用距离校正和滤波
5. 计算3D坐标
6. （可选）显示实时可视化界面

**示例输出：**
```
[0042] 位置: X= 1.234m Y= 2.567m Z= 1.123m | 静态 | 速度: 0.015m/s | Anchors: 5
```

按 `Ctrl+C` 停止定位。

## 核心算法说明

### 1. 信道质量特征提取

参考 `bu03.c:643-653` 中的诊断信息采集：

```c
dwt_rxdiag_t diag;
dwt_readdiagnostics(&diag);
ai->rxq.ciaDiag1 = diag.ciaDiag1;
ai->rxq.ipatovPeak = diag.ipatovPeak;        // 峰值
ai->rxq.ipatovPower = diag.ipatovPower;      // 功率
ai->rxq.ipatovFpIndex = diag.ipatovFpIndex;  // 首径索引
ai->rxq.ipatovAccumCount = diag.ipatovAccumCount; // 累积计数
ai->rxq.xtalOffset = diag.xtalOffset;        // 晶振偏移
```

这些参数反映了信号传播质量：
- **高SNR + 低首径索引** → LOS（视距）路径，测距准确
- **低SNR + 高首径索引** → NLOS（非视距）路径，可能存在多径效应

### 2. 距离校正流程

```
原始TWR距离 (d_raw)
    ↓
提取信道质量特征 (11维向量)
    ↓
输入机器学习模型
    ↓
预测误差 (Δd)
    ↓
校正距离: d_corrected = d_raw + Δd
```

### 3. 卡尔曼滤波

状态方程：
```
x(k) = x(k-1) + w(k)      # w ~ N(0, Q)
z(k) = x(k) + v(k)        # v ~ N(0, R)
```

其中：
- `x` 是真实距离
- `z` 是测量值（校正后）
- `Q` 是过程噪声方差（动态场景下增大）
- `R` 是测量噪声方差

更新步骤：
1. 预测：`x_pred = x_prev`
2. 卡尔曼增益：`K = P_pred / (P_pred + R)`
3. 更新：`x = x_pred + K * (z - x_pred)`

### 4. 多边定位（最小二乘法）

给定N个anchor位置 `p_i` 和距离 `d_i`，求解tag位置 `p`：

线性化方程组：
```
2(p_i - p_0)^T · p = ||p_i||² - ||p_0||² + d_0² - d_i²
```

矩阵形式：`Ax = b`，求解 `x = (A^T A)^(-1) A^T b`

## 性能优化建议

### 数据采集

1. **收集更多距离点**
   - 建议采集：0.5m, 1m, 1.5m, 2m, 2.5m, 3m...
   - 每个距离点采集500-1000个样本
   - 在不同环境条件下采集（空旷、有障碍物等）

2. **数据质量**
   - 确保真实距离准确（使用激光测距仪）
   - 保持anchor和tag高度一致
   - 避免金属反射干扰

### 模型调优

1. **增加训练数据后重新训练**
   ```python
   csv_files = ['out_0.5m.csv', 'out_1m.csv', 'out_1.5m.csv', ...]
   true_distances = [0.5, 1.0, 1.5, ...]
   ```

2. **调整超参数**
   ```python
   model.train(training_df,
               n_estimators=300,  # 增加树的数量
               max_depth=15)      # 增加树的深度
   ```

3. **尝试不同模型**
   ```python
   model = DistanceCorrectionModel(model_type='random_forest')
   ```

### 实时定位优化

1. **锚点布置**
   - 尽量形成四面体包围tag运动区域
   - 避免anchor共面
   - 高度差异化有助于Z轴定位

2. **滤波参数调整**

   编辑 `enhanced_positioning_model.py` 中的 `MotionDetector` 和 `KalmanFilter1D`：

   ```python
   # 静态场景更敏感
   self.static_threshold = 0.03  # 降低阈值

   # 卡尔曼滤波更平滑
   process_variance=0.005  # 降低过程噪声
   ```

3. **串口速率**

   如果数据量大，可以降低输出频率（编辑固件）：
   ```c
   bu03_set_rate_hz(2.0f);  // 从5Hz降到2Hz
   ```

## 扩展功能开发

### 1. 添加更多anchor

修改代码中的循环范围：
```python
for anchor_id in range(1, 8):  # 支持7个anchor
```

### 2. 导出定位轨迹

在 `realtime_positioning.py` 中添加：
```python
# 保存到CSV
with open('trajectory.csv', 'w') as f:
    f.write('timestamp,x,y,z,is_static\n')
    # 在callback中写入数据
```

### 3. 异常检测

添加NLOS检测：
```python
if channel_quality['fp_idx'] > 60:  # 首径索引过大
    print("警告: 可能存在NLOS路径")
```

### 4. 多tag支持

修改 `realtime_positioning.py`，为每个tag创建独立的 `EnhancedPositioningSystem` 实例。

## 故障排查

### 问题1: 模型训练MAE改善不明显

**原因：**
- 数据量不足
- 测量距离与真实距离差异过小（本身已经很准）
- 信道质量参数在该环境下不具有区分性

**解决：**
- 增加训练数据
- 在更复杂环境（有障碍物）下采集

### 问题2: 实时定位坐标跳动严重

**原因：**
- 锚点坐标配置错误
- 卡尔曼滤波参数不当
- 某些anchor信号质量差

**解决：**
- 重新标定anchor坐标
- 调整 `process_variance` 和 `measurement_variance`
- 在JSON解析中添加信号质量过滤

### 问题3: 串口无数据

**检查：**
- 设备是否正常连接
- 波特率是否匹配（默认2000000）
- 固件是否配置为Tag模式
- 串口权限（Linux需要 `sudo` 或添加用户到 `dialout` 组）

### 问题4: Z轴定位不准

**原因：**
- 所有anchor在同一平面（GDOP差）
- 缺少高度差异

**解决：**
- 至少一个anchor放置在不同高度
- 增加更多anchor

## 参考资料

1. **DW3000用户手册** - Qorvo官方文档
2. **DS-TWR协议** - `bu03.c` 实现
3. **Scikit-learn文档** - 机器学习算法参数说明
4. **卡尔曼滤波教程** - https://www.kalmanfilter.net/

## 联系与支持

如有问题，请检查：
1. 本文档的故障排查章节
2. 代码注释
3. `bu03.c` 中的实现细节

## 许可证

本项目代码仅供学习和研究使用。
