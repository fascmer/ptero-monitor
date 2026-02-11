# 🐉 Pterodactyl Monitor - 翼龙面板服务器监控保活

翼龙面板 (Pterodactyl Panel) 服务器监控工具，自动检测服务器状态，当服务器离线时自动发送启动命令，实现停机保活功能。

## ✨ 功能特点

- 🔄 **自动保活** - 检测到服务器 offline 状态自动发送 start 命令
- ⏱️ **自定义间隔** - 监控间隔可自定义，默认 10 秒，最小 5 秒
- 📊 **实时状态** - 显示服务器运行状态、重启次数、最后检查时间
- 📝 **操作日志** - 记录所有监控和重启操作
- 🎮 **手动控制** - 支持手动启动/重启/停止操作
- 🔐 **访问认证** - 可选的账号密码保护
- 🌐 **代理支持** - 支持 SOCKS5/HTTP 代理，绕过 Cloudflare 防护
- ⚠️ **智能提示** - 自动识别 Cloudflare 防护并提示

## 🚀 快速开始

### Docker 部署（推荐）

```bash
docker run -d \
  --name ptero-monitor \
  -p 8000:8000 \
  -v ptero-data:/app/data \
  ghcr.io/YOUR_USERNAME/ptero-monitor:latest
```

### Docker Compose

```yaml
version: '3.8'
services:
  ptero-monitor:
    image: ghcr.io/YOUR_USERNAME/ptero-monitor:latest
    container_name: ptero-monitor
    ports:
      - "8000:8000"
    volumes:
      - ptero-data:/app/data
    restart: unless-stopped

volumes:
  ptero-data:
```

### 手动部署

```bash
# 克隆项目
git clone https://github.com/YOUR_USERNAME/ptero-monitor.git
cd ptero-monitor

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 运行
python app.py
```

## 📚 使用说明

### 添加服务器

1. **服务器名称**: 起个名字方便识别
2. **API地址**: 完整的 API URL，包含服务器 ID
   ```
   https://panel.example.com/api/client/servers/a1b2c3d4
   ```
3. **API Key**: 从翼龙面板获取的 Client API Key (`ptlc_xxx`)
4. **监控间隔**: 默认 10 秒
5. **代理地址**（可选）: 如遇 Cloudflare 防护，可配置代理

### 代理格式

```
socks5://127.0.0.1:1080
http://127.0.0.1:8080
socks5://user:password@proxy.example.com:1080
```

### 设置访问认证

1. 点击右上角 **⚙️ 设置**
2. 输入用户名和密码
3. 点击保存，认证自动启用

## 🛠️ 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8000` | 监听端口 |
| `DB_PATH` | `monitor.db` | 数据库文件路径 |

## 📁 项目结构

```
ptero-monitor/
├── app.py              # 主程序
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 构建文件
├── static/
│   ├── index.html      # 主页面
│   └── login.html      # 登录页面
└── .github/
    └── workflows/
        └── docker.yml  # GitHub Actions
```

## 📦 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/servers` | 获取服务器列表 |
| POST | `/api/servers` | 添加服务器 |
| DELETE | `/api/servers/{id}` | 删除服务器 |
| PUT | `/api/servers/{id}` | 更新服务器 |
| POST | `/api/servers/{id}/toggle` | 开关监控 |
| POST | `/api/servers/{id}/power` | 电源操作 |
| GET | `/api/servers/{id}/logs` | 获取日志 |
| GET | `/api/logs` | 获取所有日志 |

## 📄 许可证

MIT License

## 🙏 致谢

- [Pterodactyl Panel](https://pterodactyl.io/) - 开源游戏服务器管理面板
- [aiohttp](https://docs.aiohttp.org/) - 异步 HTTP 客户端/服务器框架
