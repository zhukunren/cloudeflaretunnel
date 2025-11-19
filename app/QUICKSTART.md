# 快速参考

## 🚀 启动应用

```bash
# 从项目根目录
cd /home/zhukunren/桌面/项目/内网穿透
python -m app.main
```

## 🐛 遇到错误?

### Cloudflare 500 错误
```
Internal server error Error code 500
```
**不用担心!** 这是正常的,不影响使用。
- ✅ 本地功能正常
- ✅ 已有隧道可用
- 💡 忽略错误继续使用

### 导入错误
```
ImportError: attempted relative import
```
**解决**: 确保从正确路径运行
```bash
cd /home/zhukunren/桌面/项目/内网穿透
python -m app.main  # ✓ 正确
```

### 缺少依赖
```
ModuleNotFoundError: No module named 'yaml'
```
**解决**: 安装依赖
```bash
pip install pyyaml
```

## 🔧 常用命令

```bash
# 启动应用(现代UI)
python -m app.main

# 启动应用(经典UI)
python -m app.main --classic

# 运行诊断
python diagnose.py

# 安装脚本
./install.sh        # Linux/macOS
install.bat         # Windows

# 快速启动
./run.sh            # Linux/macOS
run.bat             # Windows
```

## 📁 重要文件

```
app/
├── README.md              # 项目说明
├── USAGE.md               # 使用指南
├── TROUBLESHOOTING.md     # 故障排查
├── BUGFIX.md              # Bug修复说明
├── diagnose.py            # 诊断工具
├── install.sh/bat         # 安装脚本
└── run.sh/bat             # 启动脚本
```

## 🎯 首次使用

1. **安装依赖**
   ```bash
   pip install pyyaml
   ```

2. **启动应用**
   ```bash
   python -m app.main
   ```

3. **设置 cloudflared**
   - 点击 📁 选择文件
   - 或点击 ⬇ 自动下载

4. **登录认证**
   - 点击 🔑 登录按钮
   - 在浏览器完成授权

5. **创建隧道**
   - 点击 ➕ 新建
   - 输入隧道名称

6. **配置隧道**
   - 点击 ✏ 编辑配置
   - 设置hostname和service

7. **启动隧道**
   - 选择隧道
   - 点击 ▶ 启动

## 💡 提示

- 遇到500错误 → **忽略,继续使用**
- 没有网络 → **可以管理本地隧道**
- 需要帮助 → **查看 TROUBLESHOOTING.md**
- 有问题 → **运行 diagnose.py**

## 📞 获取帮助

- 📖 完整文档: `README.md`
- 🔧 使用指南: `USAGE.md`
- 🐛 故障排查: `TROUBLESHOOTING.md`
- 🏗️ 项目结构: `STRUCTURE.md`
- 📝 变更日志: `CHANGELOG.md`

---

**记住**: 500错误是正常的,不影响使用! 😊
