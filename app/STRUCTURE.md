# 项目结构说明

## 📂 完整目录结构

```
app/
├── __init__.py              # 包初始化
├── main.py                  # 应用入口
├── modern_gui.py            # 现代UI(主界面)
├── modern_gui_backup.py     # 备份文件
├── gui.py                   # 经典UI
├── cloudflared_cli.py       # cloudflared CLI封装
│
├── components/              # UI组件库
│   ├── __init__.py
│   └── widgets.py          # 现代化组件
│
├── config/                  # 配置管理
│   ├── __init__.py
│   ├── settings.py         # 设置管理器
│   └── app_config.json     # 配置文件(自动生成)
│
├── utils/                   # 工具模块
│   ├── __init__.py
│   ├── theme.py            # 主题系统
│   └── logger.py           # 日志管理器
│
├── assets/                  # 资源文件
│   ├── icons/              # 图标
│   └── images/             # 图片
│
├── logs/                    # 日志文件(自动生成)
│   └── tunnel_YYYYMMDD.log
│
├── tunnels/                 # 隧道配置(自动生成)
│   ├── tunnel-name-1/
│   │   └── config.yml
│   └── tunnel-name-2/
│       └── config.yml
│
├── venv/                    # 虚拟环境
│
├── README.md                # 项目说明
├── USAGE.md                 # 使用指南
├── CHANGELOG.md             # 变更日志
├── STRUCTURE.md             # 本文件
└── requirements.txt         # Python依赖

```

---

## 📦 模块说明

### 核心模块

#### `main.py`
- 应用程序入口
- 命令行参数处理
- UI模式选择(modern/classic)

#### `modern_gui.py`
- 现代化主界面
- ModernTunnelManager类 - 主窗口
- ModernTunnelList类 - 隧道列表组件
- 集成Settings、LogManager

#### `gui.py`
- 经典UI界面
- ConfigEditor类 - 配置编辑器
- 向后兼容

#### `cloudflared_cli.py`
- cloudflared命令封装
- 隧道CRUD操作
- DNS路由管理
- 配置文件处理
- 下载和更新功能

---

### 组件模块 (`components/`)

#### `widgets.py`
可复用的UI组件:

**ModernButton**
- 现代化按钮
- 支持样式: primary, success, danger, warning, info, outline
- 自动悬停效果
- 图标支持

**IconButton**
- 图标按钮
- 简洁设计
- 用于工具栏

**Card**
- 卡片容器
- 带标题栏
- 内容区域

**Badge**
- 状态徽章
- 支持: default, success, warning, error, info
- 图标支持

**StatusIndicator**
- 状态指示器
- 标签+值显示
- 颜色状态

**SearchBox**
- 搜索输入框
- 自带清除按钮
- ESC键快捷清除
- 变化回调

---

### 配置模块 (`config/`)

#### `settings.py`

**Settings类**
- 配置持久化管理
- JSON格式存储
- 点号路径访问
- 自动保存/加载
- 默认配置

**配置结构**:
```python
{
  "window": {
    "width": 1200,
    "height": 700,
    "min_width": 1000,
    "min_height": 600,
    "remember_position": True,
    "x": None,
    "y": None
  },
  "cloudflared": {
    "path": "",
    "auto_find": True
  },
  "ui": {
    "theme": "modern",
    "language": "zh_CN",
    "show_sidebar": True,
    "compact_mode": False
  },
  "log": {
    "max_lines": 1000,
    "auto_scroll": True,
    "show_timestamp": True,
    "level": "info"
  },
  "tunnel": {
    "auto_route_dns": True,
    "save_last_selected": True,
    "last_selected": None
  }
}
```

---

### 工具模块 (`utils/`)

#### `theme.py`

**Theme类**
- 现代化配色方案
- 60+ 颜色常量
- 字体规范
- 间距系统
- 圆角规范
- 动画时间

**颜色系统**:
- 主色调: PRIMARY, ACCENT
- 背景色: BG_MAIN, BG_CARD, BG_TOOLBAR
- 文字色: TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
- 状态色: SUCCESS, WARNING, ERROR, INFO
- 边框色: BORDER, DIVIDER

**DarkTheme类**
- 深色主题(扩展)
- 继承Theme
- 重写颜色

#### `logger.py`

**LogLevel枚举**
- DEBUG = 0
- INFO = 1
- WARNING = 2
- ERROR = 3

**LogManager类**
- 多级日志管理
- 日志缓冲区
- 文件保存
- 回调机制
- 日志统计

**功能**:
- `debug(msg)` - 调试日志
- `info(msg)` - 信息日志
- `warning(msg)` - 警告日志
- `error(msg)` - 错误日志
- `get_logs()` - 获取日志
- `get_stats()` - 统计信息
- `export_to_string()` - 导出

---

## 🔄 数据流

```
用户操作
   ↓
modern_gui.py (UI)
   ↓
cloudflared_cli.py (业务逻辑)
   ↓
cloudflared (CLI工具)
   ↓
Cloudflare API
```

```
配置持久化:
Settings → config/app_config.json

日志记录:
LogManager → logs/tunnel_YYYYMMDD.log

隧道配置:
ConfigEditor → tunnels/{name}/config.yml
```

---

## 🎨 UI架构

```
ModernTunnelManager (主窗口)
├── Topbar (顶部导航栏)
│   ├── Logo & Title
│   ├── Version Info
│   └── Tool Buttons (Login, Download, Browse)
│
├── Main Container
│   ├── Left Panel (隧道列表)
│   │   ├── Header (标题 + 操作按钮)
│   │   ├── SearchBox (搜索框)
│   │   └── ModernTunnelList (隧道卡片列表)
│   │
│   └── Right Panel (控制和日志)
│       ├── Control Section
│       │   ├── Toggle Button (启动/停止)
│       │   └── Secondary Actions (DNS, Edit, Test)
│       │
│       ├── Status Card (系统状态)
│       │   └── Status Indicators
│       │
│       └── Log Card (运行日志)
│           ├── Log Toolbar
│           └── Log Text Widget
│
└── Statusbar (底部状态栏)
    ├── Status Text
    └── Path Indicator
```

---

## 🚀 启动流程

```
1. main.py 解析命令行参数
   ↓
2. 选择UI模式(modern/classic)
   ↓
3. modern_gui.py 启动
   ↓
4. ModernTunnelManager.__init__()
   ├── 加载Settings
   ├── 初始化LogManager
   ├── 初始化变量
   ├── 构建UI (_build_modern_ui)
   └── 初始化应用 (_init_app)
   ↓
5. _init_app()
   ├── 刷新版本信息
   ├── 刷新隧道列表
   ├── 更新状态显示
   └── 恢复窗口几何配置
   ↓
6. 进入主事件循环
```

---

## 🔧 扩展指南

### 添加新组件

1. 在 `components/widgets.py` 中定义:
```python
class MyWidget(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=Theme.BG_CARD, **kwargs)
        # 实现逻辑
```

2. 在 `components/__init__.py` 中导出:
```python
from .widgets import MyWidget
__all__ = [..., "MyWidget"]
```

3. 在界面中使用:
```python
widget = MyWidget(parent)
widget.pack()
```

### 添加新配置项

1. 在 `Settings._default_settings()` 中添加:
```python
"my_feature": {
    "enabled": True,
    "option": "value"
}
```

2. 使用配置:
```python
enabled = self.settings.get("my_feature.enabled")
self.settings.set("my_feature.option", "new_value")
```

### 添加新主题

1. 在 `utils/theme.py` 中定义:
```python
class MyTheme(Theme):
    PRIMARY = "#YOUR_COLOR"
    # 覆盖其他颜色
```

2. 注册主题:
```python
THEMES["my_theme"] = MyTheme
```

3. 使用主题:
```python
theme = get_theme("my_theme")
```

---

## 📝 代码规范

### 命名约定
- **类名**: PascalCase (如: `ModernButton`)
- **函数/方法**: snake_case (如: `get_tunnel_list`)
- **常量**: UPPER_CASE (如: `PRIMARY_COLOR`)
- **私有方法**: `_method_name`
- **保护方法**: `__method_name`

### 文件组织
- 每个模块一个职责
- 公共接口在 `__init__.py`
- 私有实现在独立文件

### 导入顺序
1. 标准库
2. 第三方库
3. 本地模块

### 注释规范
- 使用文档字符串(docstring)
- 关键逻辑添加注释
- 复杂算法详细说明

---

## 🎯 性能考虑

### UI响应性
- 耗时操作使用线程
- 避免阻塞主线程
- 异步更新UI

### 内存管理
- 限制日志缓冲区大小
- 及时清理无用对象
- 避免循环引用

### 文件操作
- 使用缓存减少读取
- 批量操作提高效率
- 异常处理避免崩溃

---

## 🐛 调试技巧

### 启用调试日志
```python
logger.set_level(LogLevel.DEBUG)
```

### 查看配置
```python
settings = Settings()
print(settings.get_all())
```

### 查看日志统计
```python
logger = LogManager()
print(logger.get_stats())
```

---

**文档版本**: 2.0.0
**更新日期**: 2025-11-18
