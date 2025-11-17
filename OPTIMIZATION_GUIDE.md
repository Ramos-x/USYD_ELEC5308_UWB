# UWB定位系统优化指南

## 优化概述

本次优化针对UWB定位系统进行了全面的代码重构和改进，主要解决了以下问题：

### 1. 修复的严重问题

#### 1.1 语法错误修复
- **文件**: `Run/xyzrange.py` (行775-820)
- **问题**: 严重的缩进错误和缺少右括号
- **修复**: 纠正了所有缩进问题，补全了缺失的括号
- **影响**: 代码现在可以正常运行

#### 1.2 导入问题修复
- **文件**: `Run/Training/realtime_positioning.py`
- **问题**: `traceback`模块在函数内部导入
- **修复**: 将导入移至文件顶部
- **影响**: 提高了性能，符合Python最佳实践

#### 1.3 资源泄露修复
- **文件**: `Run/tool/collect_uwb.py`, `Run/tool/json2csv.py`
- **问题**: 文件打开后在异常情况下未关闭
- **修复**: 使用`with`语句确保文件自动关闭
- **影响**: 避免了资源泄露和文件句柄耗尽

### 2. 新增模块

#### 2.1 统一配置管理系统

**位置**: `Run/config/`

创建了三个配置文件：
- `anchor_config.json` - 锚点坐标配置
- `system_config.yaml` - 系统参数配置
- `__init__.py` - 配置管理器

**使用方法**:

```python
from config import get_config, get_anchor_positions

# 获取配置管理器
config = get_config()

# 获取锚点坐标字典 {anchor_id: (x, y, z)}
positions = config.anchor_positions
print(positions)
# {1: (0.3, 0.3, 0.6), 2: (3.3, 0.3, 1.82), ...}

# 获取锚点坐标列表（用于numpy）
positions_list = config.anchor_positions_list
print(positions_list)
# [[0.3, 0.3, 0.6], [3.3, 0.3, 1.82], ...]

# 获取输入锚点ID列表
input_anchors = config.input_anchors
print(input_anchors)
# [1, 2, 3, 4, 5]

# 获取特定锚点信息
anchor_info = config.get_anchor_info(1)
print(anchor_info)
# {'x': 0.3, 'y': 0.3, 'z': 0.6, 'name': 'Anchor 1', ...}
```

**优势**:
- 所有锚点坐标集中管理，不再分散在多个文件中
- 修改配置只需编辑JSON文件，无需改动代码
- 支持添加更多配置项而无需修改代码

#### 2.2 共享距离计算模块

**位置**: `Run/uwb_distance.py`

提供统一的DS-TWR距离计算功能。

**使用方法**:

```python
from uwb_distance import DistanceCalculator, compute_distance_m

# 方法1: 使用便捷函数
extended_data = {
    "tx1": "0A1B2C3D4E",
    "rx1": "0A1B2C3D50",
    "tx2": "0A1B2C3D60",
    "rx2": "0A1B2C3D70",
    "tx3r": "0A1B2C3D80",
    "rx3": "0A1B2C3D90"
}
distance = compute_distance_m(extended_data)
print(f"距离: {distance:.3f} 米")

# 方法2: 使用类
calculator = DistanceCalculator()
distance = calculator.compute_distance(extended_data)

# 方法3: 自定义光速值
calculator = DistanceCalculator(speed_of_light=299792458.0)
distance = calculator.compute_distance(extended_data)
```

**优势**:
- 消除了代码重复（之前在3个文件中重复实现）
- 详细的文档和类型提示
- 统一的错误处理和验证
- 向后兼容旧代码

#### 2.3 日志系统

**位置**: `Run/uwb_logger.py`

提供统一的日志管理功能。

**使用方法**:

```python
from uwb_logger import setup_logging, get_logger

# 设置全局日志系统
setup_logging(
    name='uwb_system',
    level='INFO',
    console_output=True,
    file_output=True
)

# 获取日志记录器
logger = get_logger()

# 记录日志
logger.debug("调试信息")
logger.info("程序启动")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")

# 记录异常（包含堆栈跟踪）
try:
    # 某些操作
    pass
except Exception as e:
    logger.exception("发生异常")

# 便捷函数
from uwb_logger import info, error, exception

info("这是一条信息")
error("这是一个错误")
```

**日志输出**:

- **控制台**: 简洁格式 `[INFO] 程序启动`
- **文件**: 详细格式 `[2025-01-17 10:30:45] [uwb_system] [INFO] [main.py:42] - 程序启动`
- **文件位置**: `logs/uwb_YYYYMMDD.log`
- **自动轮转**: 单个文件最大10MB，保留5个备份

**优势**:
- 替代了散布在代码中的print语句
- 支持不同日志级别
- 自动记录时间、文件名、行号
- 支持日志文件自动轮转
- 异常时自动记录堆栈跟踪

### 3. 代码质量改进

#### 3.1 修复前的问题

1. **硬编码的值**: 锚点坐标在5个文件中重复定义
2. **重复代码**: 距离计算逻辑在3个文件中重复
3. **缺少类型提示**: 难以理解函数参数和返回值
4. **资源管理**: 文件未正确关闭
5. **错误处理**: 缺少或过于宽泛
6. **命名不清**: 变量名如`ex`、`qual`含义不明

#### 3.2 改进措施

✅ **配置集中管理**: 创建`anchor_config.json`
✅ **代码复用**: 创建`uwb_distance.py`共享模块
✅ **资源管理**: 使用`with`语句管理文件
✅ **日志系统**: 替代print，提供更好的调试能力
✅ **文档完善**: 所有新模块都有详细的docstring

### 4. 迁移指南

#### 4.1 更新现有代码使用新配置系统

**之前**:
```python
# 在xyzrange.py中
ANCHOR_POSITIONS = {
    1: (0.00, 0.00, 2.00),
    2: (4.00, 0.00, 2.00),
    # ...
}
```

**现在**:
```python
from config import get_anchor_positions

anchor_positions = get_anchor_positions()
```

#### 4.2 更新现有代码使用新距离计算模块

**之前**:
```python
# 每个文件都实现自己的compute_distance_m
def compute_distance_m(ex):
    tx1 = hex5_to_u40(ex["tx1"])
    # ...
```

**现在**:
```python
from uwb_distance import compute_distance_m

distance = compute_distance_m(extended_data)
```

#### 4.3 更新现有代码使用日志系统

**之前**:
```python
print("正在搜索串口...")
print(f"错误：未找到设备")
```

**现在**:
```python
from uwb_logger import get_logger

logger = get_logger(__name__)
logger.info("正在搜索串口...")
logger.error("未找到设备")
```

### 5. 文件结构

优化后的项目结构：

```
USYD_ELEC5308_UWB/
├── Run/
│   ├── config/                      # 新增：配置管理
│   │   ├── __init__.py              # 配置管理器
│   │   ├── anchor_config.json       # 锚点配置
│   │   └── system_config.yaml       # 系统配置
│   ├── uwb_distance.py              # 新增：距离计算模块
│   ├── uwb_logger.py                # 新增：日志系统
│   ├── logs/                        # 新增：日志文件目录
│   │   └── uwb_YYYYMMDD.log
│   ├── xyzrange.py                  # 已修复语法错误
│   ├── tool/
│   │   ├── collect_uwb.py           # 已修复资源泄露
│   │   └── json2csv.py              # 已修复资源泄露
│   └── Training/
│       ├── realtime_positioning.py  # 已修复导入问题
│       └── enhanced_positioning_model.py
├── OPTIMIZATION_GUIDE.md            # 本文档
└── ...
```

### 6. 测试建议

#### 6.1 基本语法测试

```bash
# 检查Python语法
python -m py_compile Run/xyzrange.py
python -m py_compile Run/uwb_distance.py
python -m py_compile Run/uwb_logger.py
python -m py_compile Run/config/__init__.py
```

#### 6.2 功能测试

```python
# 测试配置管理
python -c "from config import get_config; print(get_config().anchor_positions)"

# 测试距离计算
python -c "from uwb_distance import DistanceCalculator; print('OK')"

# 测试日志系统
python -c "from uwb_logger import setup_logging, info; setup_logging(); info('测试')"
```

### 7. 后续优化建议

虽然已经完成了主要的优化工作，但还有一些改进空间：

#### 7.1 短期改进
- [ ] 为主要函数添加类型提示
- [ ] 将xyzrange.py的main()函数分解为更小的函数
- [ ] 改进异常处理（使用具体的异常类型）

#### 7.2 中期改进
- [ ] 添加单元测试
- [ ] 使用PEP 8检查工具（pylint/flake8）
- [ ] 创建requirements.txt管理依赖

#### 7.3 长期改进
- [ ] 重构为模块化架构
- [ ] 添加配置验证
- [ ] 实现更完善的错误恢复机制

### 8. 兼容性说明

所有优化都保持了向后兼容性：

- ✅ 新模块不影响现有代码运行
- ✅ 提供了便捷函数用于快速迁移
- ✅ 修复的bug不改变正常代码的行为
- ✅ 可以逐步迁移，无需一次性修改所有代码

### 9. 联系与支持

如果在使用新模块时遇到问题，请参考：

1. 各模块的docstring文档
2. 本优化指南
3. 配置文件中的注释

---

**优化完成日期**: 2025-01-17
**优化版本**: v2.0
