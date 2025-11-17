# USYD_ELEC5308_UWB 项目重构路线图

## 优先级 1: 立即执行 (1-2小时)

### 任务 1.1: 创建项目配置文件
```bash
# 在项目根目录创建
touch requirements.txt
touch pyproject.toml
touch Run/__init__.py
```

**requirements.txt 内容**:
```
pyserial>=3.5
numpy>=1.20.0
pandas>=1.3.0
scikit-learn>=1.0.0
matplotlib>=3.4.0
markdown2>=2.4.0
joblib>=1.1.0
pyyaml>=5.4.0
```

**Run/__init__.py 内容**:
```python
"""USYD UWB定位系统 - Python应用层"""
__version__ = "1.0.0"
```

### 任务 1.2: 标准化代码导入
修改以下文件，使用相对导入：
- `/home/user/USYD_ELEC5308_UWB/Run/cal_dis.py` (第1-20行)
- `/home/user/USYD_ELEC5308_UWB/Run/xyzrange.py` (第1-20行)
- `/home/user/USYD_ELEC5308_UWB/Run/tool/json2csv.py` (第1-30行)

**更改前**:
```python
import json
import sys
import time
...
# 硬编码常量
C = 299_702_547.0
```

**更改后**:
```python
from Run.uwb_distance import DistanceCalculator
from Run.config import get_config
from Run.uwb_logger import get_logger

logger = get_logger(__name__)
calculator = DistanceCalculator()
```

---

## 优先级 2: 第一周 (3-5小时)

### 任务 2.1: 创建 Run/common/ 共享模块

#### 创建 `/home/user/USYD_ELEC5308_UWB/Run/common/__init__.py`
```python
"""通用工具和共享功能"""
from .uwb_utils import UWBUtils, UWBConstants
from .serial_handler import SerialHandler, find_serial_port
from .data_processor import LinkPreprocessor

__all__ = [
    'UWBUtils',
    'UWBConstants', 
    'SerialHandler',
    'find_serial_port',
    'LinkPreprocessor'
]
```

#### 创建 `/home/user/USYD_ELEC5308_UWB/Run/common/uwb_utils.py` (~80行)
提取以下内容：
- `UWBConstants` 类（物理常量）
- `UWBUtils` 类（距离计算工具）
- `ANSI_RE` 正则表达式

**来源文件**:
- cal_dis.py: 行4-20, 164-174
- xyzrange.py: 行4-20, 273-280
- json2csv.py: 行47-57
- uwb_distance.py: 行13-20

#### 创建 `/home/user/USYD_ELEC5308_UWB/Run/common/serial_handler.py` (~150行)
提取以下内容：
- `SerialReader` 类
- `find_serial_port()` 函数
- `load_calibration_config()` 函数
- `save_calibration_config()` 函数

**来源文件**:
- cal_dis.py: 行28-393
- xyzrange.py: 行134-495

**差异处理**:
- 统一配置文件路径处理
- 统一日志输出

#### 创建 `/home/user/USYD_ELEC5308_UWB/Run/common/data_processor.py` (~200行)
提取以下内容：
- `LinkPreprocessor` 类
- `Worker` 类

**来源文件**:
- cal_dis.py: 行92-498
- xyzrange.py: 行198-600

### 任务 2.2: 更新导入语句

**修改文件列表**:
1. `/home/user/USYD_ELEC5308_UWB/Run/cal_dis.py` → 导入 common
2. `/home/user/USYD_ELEC5308_UWB/Run/xyzrange.py` → 导入 common
3. `/home/user/USYD_ELEC5308_UWB/Run/tool/json2csv.py` → 导入 common
4. `/home/user/USYD_ELEC5308_UWB/Run/Training/realtime_positioning.py` → 导入 common

**更改模式**:
```python
# 旧：本地定义
def hex5_to_u40(h: str) -> int:
    return int(h, 16) & MASK40

# 新：导入使用
from Run.common import UWBUtils

# 使用
value = UWBUtils.hex5_to_u40(h)
```

### 任务 2.3: 扩展 ConfigManager
修改 `/home/user/USYD_ELEC5308_UWB/Run/config/__init__.py`

**添加支持**:
- 串口配置加载
- 处理参数加载 (MEDIAN_WIN, EMA_ALPHA等)
- 校准参数加载
- 模型参数加载

**新增方法**:
```python
class ConfigManager:
    @property
    def serial_config(self) -> Dict:
        """获取串口配置"""
        return self._config.get('serial', {})
    
    @property
    def processing_config(self) -> Dict:
        """获取数据处理配置"""
        return self._config.get('processing', {})
    
    @property
    def calibration_config(self) -> Dict:
        """获取校准配置"""
        return self._config.get('calibration', {})
```

---

## 优先级 3: 第二周 (4-6小时)

### 任务 3.1: 替换所有 print() 为 logger

**修改文件**:
- `/home/user/USYD_ELEC5308_UWB/Run/cal_dis.py`
- `/home/user/USYD_ELEC5308_UWB/Run/xyzrange.py`
- `/home/user/USYD_ELEC5308_UWB/Run/Training/realtime_positioning.py`
- `/home/user/USYD_ELEC5308_UWB/Run/tool/json2csv.py`

**替换模式**:
```python
# 旧
print(f"[DEBUG] 检测到 {waiting} 字节待读取")

# 新
logger.debug(f"检测到 {waiting} 字节待读取")
```

**删除**:
- 所有 `DEBUG_MODE` 条件检查
- 所有 `if DEBUG_MODE:` 块
- `OUTPUT_ON_COMPLETE_UART` 标志

### 任务 3.2: 优化定位算法

修改 `/home/user/USYD_ELEC5308_UWB/Run/xyzrange.py` 的 `multilaterate_3d()` 函数

**改进点**:
1. 自适应步长: `step = 0.5 / (i + 1)`
2. 避免平方根: 使用平方值比较
3. 早期停止: 改进收敛检查

**预期收益**: 计算量↓20-30%, 精度↑10%

### 任务 3.3: 合并 cal_dis.py → xyzrange.py

**计划**:
1. 分析两个文件的差异
2. 将独特功能从 cal_dis.py 合并到 xyzrange.py
3. 删除 cal_dis.py
4. 更新所有导入

**预期代码减少**: ~700行

---

## 优先级 4: 长期优化 (1-2周)

### 任务 4.1: C固件代码拆分 (deca_device.c: 4691行)

**拆分计划**:
```
deca_device.c (4691行)
  ├─ deca_device_core.c (~1500行) - 核心驱动
  ├─ deca_device_regs.c (~1500行) - 寄存器操作
  ├─ deca_device_init.c (~1000行) - 初始化序列
  └─ deca_device_common.h - 共享声明
```

### 任务 4.2: ML模型优化

修改 `/home/user/USYD_ELEC5308_UWB/Run/Training/enhanced_positioning_model.py`

**优化**:
- 模型序列化 (.pkl)
- 动态加载支持
- 缓存机制

### 任务 4.3: DMA集成 (C固件)

实施 DMA 替代忙轮询：
- SPI DMA
- UART DMA  
- OLED DMA (可选)

**预期收益**: 功耗↓20-30%, CPU占有率↓40%

---

## 验证清单

### 重构前检查
- [ ] 备份所有源代码
- [ ] 创建新分支: `git checkout -b refactor/code-consolidation`
- [ ] 编译检查：所有模块可导入

### 重构中检查
- [ ] 每个小步骤后运行单元测试
- [ ] 确保所有文件都使用相同的配置
- [ ] 验证日志输出一致

### 重构后检查
- [ ] 功能测试：所有脚本正常运行
- [ ] 性能测试：没有性能退化
- [ ] 代码审查：检查是否有遗留的重复

---

## 预期成果

### 重构前
- 总代码: 5,764行 Python
- 重复代码: 400-500行
- 维护性评分: 6/10

### 重构后
- 总代码: 5,100-5,300行 Python
- 重复代码: <50行
- 维护性评分: 8.5/10
- 性能提升: +5-10%（减少DEBUG检查）

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|-----|------|------|---------|
| 破坏现有功能 | 中 | 高 | 详细测试, git分支 |
| 导入错误 | 中 | 中 | 模块化导入, 自动化测试 |
| 配置文件格式变更 | 低 | 中 | 向后兼容性, 迁移脚本 |
| C代码编译失败 | 低 | 高 | 增量拆分, 编译检查 |

---

## 时间表（建议）

```
Week 1:
  Monday:    任务 1.1, 1.2 (2h)
  Tuesday:   任务 2.1, 2.2 (3h)
  Wednesday: 任务 2.3 (1h)
  Thursday:  测试和验证 (2h)
  Friday:    文档和总结 (1h)

Week 2:
  Monday:    任务 3.1, 3.2 (3h)
  Tuesday:   任务 3.3 (3h)
  Wednesday: 集成测试 (2h)
  Thursday:  性能基准测试 (2h)
  Friday:    bug修复和文档 (2h)

Week 3-4:
  低优先级任务 (长期)
```

---

**下一步**: 从任务 1.1 开始！

