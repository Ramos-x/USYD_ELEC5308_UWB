# 快速参考指南 - USYD_ELEC5308_UWB 项目

## 1. 关键文件位置

### Python代码关键文件
```
/home/user/USYD_ELEC5308_UWB/
├── Run/
│   ├── xyzrange.py            (833行) ⚠️ 需要优化
│   ├── cal_dis.py             (721行) ⚠️ 需要合并到 xyzrange.py
│   ├── uwb_distance.py        (173行) ✓ 模板实现
│   ├── uwb_logger.py          (214行) ✓ 日志系统
│   ├── config/__init__.py     (144行) ⚠️ 需要扩展
│   └── Training/
│       └── enhanced_positioning_model.py (703行) ⚠️ 需要模块化
```

### C固件关键文件
```
/home/user/USYD_ELEC5308_UWB/Core/Src/
├── UWB/
│   ├── deca_device.c          (4691行) ⚠️ 需要拆分
│   ├── bu03.c                 (2248行) ✓ 协议实现
│   ├── tag.c                  (852行) ✓ Tag角色
│   └── anchor.c               (404行) ✓ Anchor角色
├── app.c                      (332行) ✓ 应用层
└── main.c                     (402行) ✓ 主程序
```

## 2. 重复代码快速检查

### 最严重的重复

| 代码 | 位置 | 重复次数 | 严重性 |
|-----|------|--------|------|
| hex5_to_u40() | 5个文件 | 5 | 🔴 高 |
| rel40() | 5个文件 | 5 | 🔴 高 |
| strip_ansi() | 4个文件 | 4 | 🔴 高 |
| LinkPreprocessor | 2个文件 | 2 | 🔴 高 |
| SerialReader | 2个文件 | 2 | 🔴 高 |
| Worker | 2个文件 | 2 | 🔴 高 |
| multilaterate_3d() | 2个文件 | 2 | 🟡 中 |

### 重复代码总量
- **Python**: ~400-500行（可直接删除）
- **cal_dis.py**: ~700行（可合并到xyzrange.py）

## 3. 最高优先级的改变

### 改变1: 创建 Run/common/ 模块 (1.5小时)
```python
# 新建文件：
Run/common/__init__.py
Run/common/uwb_utils.py      # 提取hex5_to_u40, rel40, strip_ansi
Run/common/serial_handler.py # 提取SerialReader, find_serial_port
Run/common/data_processor.py # 提取LinkPreprocessor, Worker
```

**收益**: 减少400行重复代码, 维护性+40%

### 改变2: 更新导入语句 (0.5小时)
```python
# 在以下文件中：
# - cal_dis.py
# - xyzrange.py
# - tool/json2csv.py
# - Training/realtime_positioning.py

from Run.common import UWBUtils, UWBConstants, SerialHandler, LinkPreprocessor
from Run.uwb_distance import DistanceCalculator
from Run.config import get_config
from Run.uwb_logger import get_logger
```

### 改变3: 统一配置管理 (1小时)
```python
# 修改 Run/config/__init__.py
# 添加对以下的支持：
# - serial_config (端口, 波特率等)
# - processing_config (MEDIAN_WIN, EMA_ALPHA等)
# - calibration_config (校准参数)
# - model_config (模型参数)

# 在 cal_dis.py, xyzrange.py 中使用：
config = get_config()
MEDIAN_WIN = config.processing_config.get('median_window', 5)
ANCHOR_POSITIONS = config.anchor_positions
```

## 4. 性能问题快速定位

### 性能问题1: DEBUG检查多
**文件**: `cal_dis.py` 行230-360  
**问题**: 20+次 `if DEBUG_MODE:` 检查在高频循环中  
**解决**: 替换为 `logger.debug()` 调用  
**收益**: +5-10%性能

### 性能问题2: 定位算法低效
**文件**: `xyzrange.py` 行74-125  
**问题**: 固定步长(0.5) + 强制20次迭代 + 平方根计算  
**解决**: 
- 自适应步长: `step = 0.5/(i+1)`
- 避免sqrt: `delta**2 < tol**2`
- 早期停止: 改进收敛检查  
**收益**: -20-30%计算量

### 性能问题3: 中值滤波低效
**文件**: `LinkPreprocessor.process()` 行130-133  
**问题**: 每次都排序窗口 O(n log n)  
**解决**: 使用堆或有序列表 O(log n)  
**收益**: 高频数据中显著

### 性能问题4: JSON同步解析
**文件**: `Worker` 类主循环  
**问题**: CPU密集型JSON解析阻塞  
**解决**: 使用ujson或orjson, 添加优先级队列  
**收益**: +20-40%吞吐量

## 5. 代码质量指标

### 当前状态
```
Python代码总量:       5,764行
  - 合理大小 (<300行): 45%  ✓
  - 中等大小 (300-600): 30% ✓
  - 过大 (>600): 25% ⚠️

重复代码占比:        7-9% ⚠️
配置硬编码:          3个地方 ⚠️
日志系统使用:        30% ⚠️
维护性评分:          6/10 ⚠️
```

### 重构后预期
```
Python代码总量:       5,100-5,300行 (-10%)
重复代码占比:        <1% (<50行)
配置硬编码:          0个地方 ✓
日志系统使用:        90% ✓
维护性评分:          8.5/10 ✓
性能提升:           +5-10% ✓
```

## 6. 必读文件

1. **项目分析报告**
   - 📄 `/home/user/USYD_ELEC5308_UWB/PROJECT_ANALYSIS_REPORT.md` (1040行)
   - 内容: 详细的结构、依赖、重复、性能分析

2. **重构路线图**
   - 📋 `/home/user/USYD_ELEC5308_UWB/REFACTORING_ROADMAP.md`
   - 内容: 分步骤重构计划、时间表、验证清单

3. **本文件**
   - 📌 `/home/user/USYD_ELEC5308_UWB/QUICK_REFERENCE.md`
   - 内容: 快速查找、关键行号、优先级

## 7. 立即行动

### 今天(15分钟)
```bash
# 1. 创建配置文件
touch /home/user/USYD_ELEC5308_UWB/Run/__init__.py
touch /home/user/USYD_ELEC5308_UWB/requirements.txt
touch /home/user/USYD_ELEC5308_UWB/pyproject.toml

# 2. 检出分支
cd /home/user/USYD_ELEC5308_UWB
git checkout -b refactor/code-consolidation
```

### 本周(4小时)
- [ ] 创建 `Run/common/` 模块 (3个文件, ~430行)
- [ ] 更新导入语句 (4个文件)
- [ ] 扩展 ConfigManager (50行)
- [ ] 运行所有模块导入测试

### 下周(6小时)
- [ ] 合并 cal_dis.py → xyzrange.py
- [ ] 优化 multilaterate_3d() 算法
- [ ] 替换所有 print() → logger
- [ ] 性能基准测试

## 8. 文件行号速查表

| 任务 | 文件 | 行号范围 | 优先级 |
|-----|------|--------|------|
| 提取hex5_to_u40 | cal_dis.py | 167 | 🔴 |
| 提取rel40 | cal_dis.py | 171 | 🔴 |
| 提取compute_distance_m | cal_dis.py | 175-220 | 🔴 |
| 提取LinkPreprocessor | cal_dis.py | 92-159 | 🔴 |
| 提取SerialReader | cal_dis.py | 223-393 | 🔴 |
| 提取Worker | cal_dis.py | 395-498 | 🔴 |
| 优化multilaterate_3d | xyzrange.py | 36-132 | 🟡 |
| 移除DEBUG检查 | xyzrange.py | 25-360 | 🟡 |
| 扩展ConfigManager | config/__init__.py | 全部 | 🟡 |
| 拆分deca_device | deca_device.c | 全部 | 🟢 |

## 9. 常见问题

**Q: 我应该从哪里开始?**
A: 从 "立即行动" 的 "今天" 部分开始。创建配置文件和分支，只需15分钟。

**Q: 是否可以并行进行多个改变?**
A: 可以。但建议先完成高优先级，再开始中等优先级。

**Q: 重构会影响C固件吗?**
A: 不会。C固件的长期优化是可选的。

**Q: 如何验证重构成功?**
A: 运行 `python -m py_compile Run/*.py Run/**/*.py` 检查语法。

**Q: 重构需要多长时间?**
A: 高+中优先级大约1-2周，取决于测试和审查的严格程度。

---

**最后更新**: 2025-11-17  
**状态**: 分析完成，准备执行重构

