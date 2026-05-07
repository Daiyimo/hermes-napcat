# Hermes-NapCat Adapter

QQ 消息平台适配器，通过 [NapCat](https://napneko.github.io) 的 OneBot 11 协议接入 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 框架。

| 依赖 | 版本 |
|------|------|
| Hermes Agent | v0.11.0 |
| NapCat | v4.18.1+ |
| Python | >= 3.11 |
| websockets | >= 14.0 |
| httpx | >= 0.27.0 |

> 如果 Hermes Agent 已通过 `.[all]` 安装，`websockets` 和 `httpx` 已包含在内。手动安装适配器时可用 `pip install websockets httpx` 补全依赖。

📚 [文档索引](docs/INDEX.md) · [变更日志](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md)

---

## 快速开始

### 1. 安装

**一键安装（推荐）**

```bash
# ── curl（推荐）──────────────────────────────────────────────
# 国内服务器（走 gh-proxy 代理）
curl -fsSL https://gh-proxy.com/https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/install.sh | bash

# 直连 GitHub
curl -fsSL https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/install.sh | bash

# ── wget（curl 不可用时）──────────────────────────────────────
# 国内服务器（走 gh-proxy 代理）
wget -qO- https://gh-proxy.com/https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/install.sh | bash

# 直连 GitHub
wget -qO- https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/install.sh | bash
```

> **⚠️ 重要**: 如果 `hermes gateway` 已在运行，安装后**必须重启**使平台注册生效：
> ```bash
> hermes gateway restart
> ```

**手动安装**

```bash
# 1. 克隆到 Hermes 平台目录
cd /opt/hermes/gateway/platforms
git clone https://github.com/Daiyimo/hermes-napcat.git napcat

# 2. 安装依赖（如果 Hermes 未安装 .[all] extras）
pip install -r /opt/hermes/gateway/platforms/napcat/requirements.txt
```

### 2. 配置

运行 Hermes 交互式配置向导：

```bash
hermes gateway setup
```

在平台列表中选择 **NapCat (QQ)**，按提示填写：

- NapCat HTTP API 地址（如 `http://127.0.0.1:3000`）
- WebSocket 地址（如 `ws://127.0.0.1:3001`）
- WS 模式（`forward` 或 `reverse`）
- 可选：访问令牌、白名单、管理员等

配置自动写入 `.env`，无需手动编辑。

### 3. 启动

```bash
hermes gateway          # 前台启动（可看日志）
hermes gateway start    # 后台启动
hermes status           # 查看各组件状态
```

---

## NapCat 配置示例

详细的 NapCat 配置（正向/反向模式）见 [配置文档](docs/CONFIGURATION.md)。

快速参考：

**正向模式（推荐）：**
- NapCat 启用 `websocketServers`（默认端口 3001）
- 适配器配置：`NAPCAT_WS_URL=ws://127.0.0.1:3001` + `NAPCAT_WS_MODE=forward`

**反向模式：**
- NapCat 配置 `websocketClients` 指向适配器（如 `ws://127.0.0.1:3002`）
- 适配器配置：`NAPCAT_WS_URL=ws://127.0.0.1:3002` + `NAPCAT_WS_MODE=reverse`

> ⚠️ `messagePostFormat` 必须设为 `"array"`

---

## 功能支持

| 功能 | 支持 | 说明 |
|------|------|------|
| 私聊/群聊消息 | ✅ | 收发文本、图片、语音、视频、文件 |
| 图片接收/发送 | ✅ | 自动下载缓存，支持 URL 和本地路径 |
| 合并转发消息 | ✅ | 自动展开（最多 10 条） |
| 处理状态提示 | ✅ | 消息处理时贴表情（思考 → 👍/😡） |
| 群管理命令 | ✅ | `/mute /ban /kick /status /ping /help`（需管理员权限） |
| 用户授权 | ✅ | 基于 QQ 号白名单 |
| 消息分块 | ✅ | 超长消息自动拆分（>4500 字符） |
| Markdown 转换 | ✅ | 自动去除 markdown 格式 |
| SSRF 防护 | ✅ | 阻止媒体下载重定向到内网 |
| 定时任务投递 | ✅ | `deliver: napcat:<QQ号>` |
| 消息撤回 | ✅ | `delete_message` API |
| 跨平台发送 | ✅ | `send_message` 工具支持 |

---

## 运维工具

项目内置完整的运维工具链，位于 `scripts/` 目录：

| 脚本 | 用途 |
|------|------|
| `scripts/diagnose.sh` | 全量诊断（环境、依赖、连通性） |
| `scripts/health-check.sh` | 快速健康检查（支持 `--json` 输出） |
| `scripts/logs-tail.sh` | 日志实时查看（NapCat 高亮） |
| `scripts/quick-setup-env.sh` | 交互式 `.env` 配置 |
| `scripts/test-message.sh` | 消息发送测试（绕过 Hermes） |

```bash
# 快速诊断
bash scripts/diagnose.sh

# 健康检查（JSON 输出，适合监控）
bash scripts/health-check.sh --json

# 实时查看日志
bash scripts/logs-tail.sh -n 100 --grep napcat
```

---

## 故障排查

常见问题排查见 [故障排查文档](docs/TROUBLESHOOTING.md)。

快速命令：

```bash
hermes status           # 查看 NapCat 平台配置状态
hermes status --deep    # 深度检查（含端口连通性）
hermes doctor           # 运行完整诊断
```

---

## 开发与测试

```bash
# 运行单元测试
cd tests
python -m pytest . -v

# 带覆盖率报告
pip install pytest-cov
cd tests
python -m pytest . -v --cov=.. --cov-report=term-missing
```

测试不依赖真实 NapCat 或 Hermes Gateway，所有网络依赖通过 `tests/conftest.py` 中的 stub 隔离。

详细开发指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

MIT License — 与 Hermes Agent 一致。
