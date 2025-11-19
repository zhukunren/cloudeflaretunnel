Cloudflare 内网穿透 GUI (cloudflared)

简介
- 一个基于 Python Tkinter 的轻量 GUI，用于通过 Cloudflare Tunnel(cloudflared) 管理内网穿透：登录、查看/创建/删除隧道、编辑配置、启动/停止隧道、DNS 路由。

环境要求
- Windows 10/11（其它平台理论可用）
- 安装 Python 3.9+（自带 Tkinter）
- 安装 cloudflared 并加入 PATH
  - 不想手动下载？在 GUI 顶部点击“下载”，自动获取并保存 cloudflared 可执行文件。

安装 cloudflared
1) 到 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 下载对应平台的 cloudflared
2) 将可执行文件放到某个目录，并把该目录加入 PATH；或在 GUI 里手动选择 cloudflared 路径

快速开始
1) 首次授权：运行登录
   - 打开 GUI 后，点击“登录”，在浏览器完成 Cloudflare 账户授权（绑定你要使用的域名/账户）。
2) 运行应用
   - 在项目目录执行：
     - `python -m app.main`
3) 隧道管理
   - 刷新：列出当前账户下的隧道
   - 下载：自动下载 cloudflared（Windows/架构自动匹配）
   - 新建隧道：输入名称后创建
   - 编辑配置：为选中隧道生成/打开 `tunnels/<name>/config.yml`，可配置 ingress 映射
   - 启动/停止：基于该配置启动或停止隧道进程
   - DNS 路由：一键为选中隧道绑定域名（创建 Cloudflare DNS 记录）
   - 删除选中：删除远端隧道（不可恢复）

配置说明
- 生成的配置文件示例：

  ```yaml
  tunnel: <隧道ID>
  credentials-file: C:/Users/<User>/.cloudflared/<隧道ID>.json
  ingress:
    - hostname: app.example.com
      service: http://localhost:8080
    - service: http_status:404
  ```

- credentials-file：由 cloudflared create/login 生成在系统默认目录（Windows: `%USERPROFILE%\.cloudflared`）。
- ingress：
  - 若需将本机 8080 暴露为 `app.example.com`，设置如上并在 GUI 里点击“启动”。
  - 还需执行 DNS 路由（可在 GUI 点击“DNS 路由”，或命令行手动执行）：
    - `cloudflared tunnel route dns <隧道名> <hostname>`

常见流程
1) `登录` → `新建隧道` → `编辑配置` 填写 hostname 和本地服务 → 在 DNS 托管于 Cloudflare 的域名下添加路由（GUI 的“DNS 路由”）→ `启动`。

故障排查
- 登录/创建隧道报错：确保浏览器完成授权，账户下已绑定域。
- 启动失败：打开日志面板查看输出信息；检查 `credentials-file` 路径是否存在。
- 无法访问域名：确认在 Cloudflare 面板中域名 DNS 记录已由 `cloudflared tunnel route dns` 创建且为代理状态。

开发说明
- 入口：`app/main.py`
- GUI：`app/gui.py`
- cloudflared 封装：`app/cloudflared_cli.py`

命令速查
- 登录：`cloudflared login`
- 列表：`cloudflared tunnel list --output json`
- 创建：`cloudflared tunnel create <name>`
- 路由：`cloudflared tunnel route dns <name> <hostname>`
- 运行：`cloudflared --config <config> tunnel run <name>`
- 删除：`cloudflared tunnel delete <name>`
