# Hermes-NapCat Adapter

QQ 消息平台适配器，通过 [NapCat](https://napneko.github.io) 的 OneBot 11 协议接入 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 框架。

| 依赖 | 版本 |
|------|------|
| Hermes Agent | v0.11.0 |
| NapCat | v4.18.1+ |
| Python | >= 3.11 |
| websockets | >= 14.0 |
| httpx | >= 0.27.0 |

> 如果 Hermes Agent 已通过 `.[all]` 安装，`websockets` 和 `httpx` 已包含在内。手动安装适配器时可用 `pip install -r requirements.txt` 补全依赖。

---

## 架构

### 正向模式（默认）：适配器 → NapCat WS Server

```
NapCat (QQ 客户端)                    Hermes NapCat Adapter
┌──────────────────────┐              ┌──────────────────────┐
│ WS Server  :3001     │◄── ws ──────│ WS Client (接收事件)  │
│ HTTP Server :3000    │◄── POST ────│ HTTP Client (发送API) │
└──────────────────────┘              └──────────────────────┘
                                               │
                                               ▼
                                       handle_message(event)
                                               │
                                               ▼
                                         Hermes Gateway
```

### 反向模式：NapCat WS Client → 适配器 WS Server

```
NapCat (QQ 客户端)                    Hermes NapCat Adapter
┌──────────────────────┐              ┌──────────────────────┐
│ WS Client → :3002    │── ws ──────►│ WS Server (接收事件)  │
│ HTTP Server :3000    │◄── POST ────│ HTTP Client (发送API) │
└──────────────────────┘              └──────────────────────┘
                                               │
                                               ▼
                                       handle_message(event)
                                               │
                                               ▼
                                         Hermes Gateway
```

- **事件流**: NapCat 推送 OneBot 11 事件 → 适配器解析 → 构建 `MessageEvent` → 调用 `handle_message()`
- **发送流**: 适配器构建 OneBot 11 消息段数组 → HTTP POST 到 NapCat `/send_msg`
- **处理钩子**: 消息开始处理时贴"思考"表情，完成后根据成功/失败替换为 👍/😡
- **WS 模式**: 通过 `NAPCAT_WS_MODE` 切换 `forward`（默认）或 `reverse`

---

## 文件结构

```
hermes-napcat/
├── __init__.py           # 包导出 + platform_registry 自动注册
├── adapter.py            # 主适配器类 (BasePlatformAdapter 子类)
├── constants.py          # 协议常量、超时、API 端点
├── event_parser.py       # OneBot 11 事件 → MessageEvent 转换 + 转发消息展开
├── group_commands.py     # 群管理命令处理（/mute /kick /status /ping /help）
├── message_builder.py    # 文本/媒体 → OneBot 11 消息段数组构建
├── utils.py              # HTTP 客户端辅助、QQ 号脱敏
├── plugin.yaml           # 网关自动发现清单（无需手动打补丁）
├── requirements.txt      # Python 依赖清单
├── install.sh            # curl 入口包装（下载并执行 scripts/install.sh）
├── .gitignore
├── README.md
└── scripts/
    ├── install.sh        # 主安装脚本（自动检测 + 克隆 + 全链路平台注册修补）
    ├── diagnose.sh       # 诊断工具（检查依赖、配置、连通性）
    ├── health-check.sh   # 快速健康检查（支持 --json 输出）
    ├── logs-tail.sh      # 日志实时查看（NapCat 高亮）
    ├── quick-setup-env.sh # 交互式 .env 配置（不依赖 hermes gateway setup）
    └── test-message.sh   # 直接 API 测试消息发送
```

---

## 安装

### 一键安装（推荐）

在服务器上执行，选择 `curl` 或 `wget` 其中一种：

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

> `wget` 在绝大多数 Linux 发行版中内置，如仍不可用可先安装：`apt install wget` 或 `yum install wget`。

脚本会自动完成：

1. 将适配器克隆到 hermes 的 `gateway/platforms/napcat/`
2. 修补 `hermes_cli/gateway.py` — 添加 NapCat 交互式配置向导
3. 修补 `hermes_cli/platforms.py`、`tools/send_message_tool.py`、`config.yaml` — 完成平台全链路注册 + 注入 `_send_napcat` 发送函数

安装完成后直接跳到[配置](#3-配置)章节。

> **⚠️ 重要**: 如果 `hermes gateway` 已在运行，安装后**必须重启**使平台注册生效，否则会报 `KeyError: 'napcat'`：
> ```bash
> hermes gateway restart
> ```

> 适配器通过 `plugin.yaml` + `platform_registry` 注册，安装脚本已自动完成所有必要的平台注册修补，**无需手动干预**。

---

### 手动安装

#### 1. 安装 Hermes Agent

如果尚未安装，先完成 Hermes Agent 安装：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

详见 [Hermes Agent 文档](https://hermes-agent.nousresearch.com/docs/)。

#### 2. 安装适配器

```bash
# 方式一：运行安装脚本（推荐）
git clone https://github.com/Daiyimo/hermes-napcat.git
cd hermes-napcat
bash scripts/install.sh /opt/hermes    # 指定 hermes 安装目录

# 方式二：手动克隆到 Hermes Agent 的平台目录
cd /opt/hermes/gateway/platforms
git clone https://github.com/Daiyimo/hermes-napcat.git napcat
```

#### 2.5. 安装 Python 依赖

如果 Hermes Agent 未安装 `.[all]` extras，需手动安装适配器依赖：

```bash
pip install -r /opt/hermes/gateway/platforms/napcat/requirements.txt
```

### 3. 配置

安装完成后，运行 Hermes 交互式配置向导：

```bash
hermes gateway setup
```

在平台列表中选择 **NapCat (QQ)**，向导会全程中文引导，按提示依次填写：

```
─── 🐧 NapCat (QQ) 配置向导 ───

  1. 安装并运行 NapCat v4.18.1+（https://napneko.github.io）
  2. 登录 QQ 账号，在 NapCat 网络配置中启用 HTTP Server（默认端口 3000）
  3. 正向模式：启用 WebSocket Server（默认端口 3001）
   反向模式：启用 WebSocket Client（填写适配器地址 ws://127.0.0.1:3002）
  4. 将 messagePostFormat 均设为 array
  5. 如需 Token 鉴权，在 Server/Client 中填写相同的 token 字段

  NapCat HTTP Server 地址，例如 http://127.0.0.1:3000
  NapCat HTTP API 地址: http://127.0.0.1:3000

  NapCat WebSocket 地址
  NapCat WebSocket 地址: ws://127.0.0.1:3001

  WS 连接模式：forward = 适配器连接 NapCat WS Server（正向，默认）
              reverse = NapCat 连接适配器 WS Server（反向，用于 websocketClients）
  WS 模式 (forward/reverse，默认 forward): forward

  与 NapCat Server 配置中 token 字段保持一致，未配置 token 则直接回车跳过
  访问令牌（可选，留空跳过）:

  白名单：仅允许填写的 QQ 号私聊触发机器人，留空则所有人均可使用
  允许私聊的 QQ 号（逗号分隔，留空则不限制）: 123456789

  群聊白名单：仅允许填写的 QQ 号在群聊中 @ 触发机器人，留空则群内所有人均可触发
  允许群聊触发的 QQ 号（逗号分隔，留空则不限制）:

  拥有 /mute /kick /ban 等管理命令权限的 QQ 号，多个用英文逗号分隔
  管理员 QQ 号（逗号分隔，留空跳过）: 123456789

  定时任务结果的默认投递目标：私聊填 QQ 号，群聊填 g:<群号>（例如 g:123456789）
  默认投递目标（留空跳过）: 123456789

🐧 NapCat (QQ) 配置完成！
```

配置会自动写入 Hermes 的 `.env` 文件，无需手动编辑。

### 4. 启动

```bash
hermes gateway          # 前台启动（可看日志）
hermes gateway start    # 以服务方式后台启动
hermes status           # 查看各组件状态
```

启动后在 QQ 中向机器人发送消息即可开始对话。

---

## NapCat 侧配置

安装并运行 [NapCat](https://napneko.github.io) v4.18.1+，登录 QQ 账号后，编辑 `onebot11_<QQ号>.json`。

### 正向 WebSocket 模式（推荐，默认）

适配器作为客户端连接 NapCat 的 WS Server（`websocketServers`）：

```json
{
  "network": {
    "httpServers": [
      {
        "name": "hermesHttp",
        "enable": true,
        "port": 3000,
        "host": "0.0.0.0",
        "messagePostFormat": "array",
        "token": ""
      }
    ],
    "websocketServers": [
      {
        "name": "hermesWs",
        "enable": true,
        "host": "0.0.0.0",
        "port": 3001,
        "messagePostFormat": "array",
        "reportSelfMessage": false,
        "token": "",
        "heartInterval": 30000
      }
    ]
  }
}
```

适配器配置：
```bash
NAPCAT_HTTP_URL=http://127.0.0.1:3000
NAPCAT_WS_URL=ws://127.0.0.1:3001
NAPCAT_WS_MODE=forward
```

### 反向 WebSocket 模式

适配器作为 WS Server，NapCat 作为客户端连接过来（`websocketClients`）：

```json
{
  "network": {
    "httpServers": [
      {
        "name": "hermesHttp",
        "enable": true,
        "port": 3000,
        "host": "0.0.0.0",
        "messagePostFormat": "array",
        "token": ""
      }
    ],
    "websocketClients": [
      {
        "name": "hermesReverseWs",
        "enable": true,
        "url": "ws://127.0.0.1:3002",
        "messagePostFormat": "array",
        "reportSelfMessage": false,
        "token": "",
        "reconnectInterval": 5000
      }
    ]
  }
}
```

适配器配置：
```bash
NAPCAT_HTTP_URL=http://127.0.0.1:3000
NAPCAT_WS_URL=ws://127.0.0.1:3002
NAPCAT_WS_MODE=reverse
```

> **重要**: `messagePostFormat` 必须设为 `"array"`，适配器依赖消息段数组格式。

---


---

## Docker 部署

同一台设备上 NapCat + Hermes 各一个容器，推荐 **Forward 模式**：

```yaml
# docker-compose.yml
services:
  napcat:
    image: your-napcat-image
    container_name: napcat
    ports:
      - "3000:3000"    # HTTP API — Hermes 需要调
    # WS Server 3001 不需要映射到宿主机，容器间内网即可

  hermes:
    image: your-hermes-image
    container_name: hermes
    environment:
      NAPCAT_HTTP_URL: http://napcat:3000
      NAPCAT_WS_URL: ws://napcat:3001
      NAPCAT_WS_MODE: forward
    depends_on:
      - napcat
```

NapCat 侧配 `websocketServers` 开 3001，Hermes 侧用容器名 `napcat` 作为主机名直连。详情见上方 [正向 WebSocket 模式](#正向-websocket-模式推荐默认)。

## 环境变量参考

以下变量由 `hermes gateway setup` 自动配置，也可手动编辑 `.env`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `NAPCAT_HTTP_URL` | 是 | NapCat HTTP API 地址，如 `http://127.0.0.1:3000` |
| `NAPCAT_WS_URL` | 是 | NapCat WebSocket 地址。正向模式填入 NapCat WS 服务器地址，如 `ws://127.0.0.1:3001`；反向模式填入适配器监听地址，如 `ws://127.0.0.1:3002` |
| `NAPCAT_WS_MODE` | 否 | WebSocket 模式：`forward`（适配器连接 NapCat，默认）或 `reverse`（NapCat 连接适配器，对应 NapCat 的 websocketClients 配置） |
| `NAPCAT_TOKEN` | 否 | NapCat 访问令牌（与 NapCat 配置中的 token 字段一致） |
| `NAPCAT_HOME_CHANNEL` | 否 | 默认投递目标（QQ 号或群号，用于定时任务投递） |
| `NAPCAT_ALLOWED_USERS` | 否 | 允许私聊的 QQ 号，逗号分隔（为空则不限制所有人） |
| `NAPCAT_GROUP_ALLOWED_USERS` | 否 | 群聊中允许触发的 QQ 号，逗号分隔（优先级高于全局名单） |
| `NAPCAT_ALLOW_ALL_USERS` | 否 | 设为 `true` 允许所有用户（默认：未配置白名单时等同于允许所有人） |
| `NAPCAT_ADMIN_USERS` | 否 | 管理员 QQ 号，逗号分隔，允许执行 /mute /kick 等命令（管理员自动绕过授权白名单） |
| `NAPCAT_REQUIRE_MENTION` | 否 | 群聊是否需要 @机器人 才触发（默认 `true`） |
| `NAPCAT_ENABLE_REACTIONS` | 否 | 是否启用处理状态贴表情（思考 → 👍/😡，默认 `true`） |

---

## 功能支持

| 功能 | 支持 | 说明 |
|------|------|------|
| 私聊消息 | ✅ | 收发文本、图片、语音、视频、文件 |
| 群聊消息 | ✅ | 收发文本、图片、语音、视频、文件 |
| 图片接收 | ✅ | 自动下载并缓存 |
| 图片发送 | ✅ | 支持 URL 和本地文件路径 |
| 语音消息 | ✅ | 收发语音（record 类型） |
| 视频消息 | ✅ | 收发视频 |
| 文件传输 | ✅ | 收发文件（file 类型） |
| 消息引用 | ✅ | reply 消息段 |
| @提及 | ✅ | 解析为 `@昵称` 文本 |
| @触发 | ✅ | 群聊中需要 @机器人 才触发（可通过 `NAPCAT_REQUIRE_MENTION=false` 关闭） |
| QQ 表情 | ✅ | 102 个 QQ face → Unicode emoji 映射 |
| 合并转发消息 | ✅ | 调用 `/get_forward_msg` 展开节点内容（最多 10 条，每条最长 200 字符） |
| 处理状态提示 | ✅ | 消息开始处理时贴"思考"表情（face 32），完成后替换为 👍（成功）或 😡（失败） |
| 群管理命令 | ✅ | `/mute /ban /kick /status /ping /help`（需设置 `NAPCAT_ADMIN_USERS`） |
| 用户授权 | ✅ | 基于 QQ 号白名单，管理员自动绕过授权检查 |
| 消息分块 | ✅ | 超长消息（>4500 字符）自动拆分发送，块间限速 300ms |
| Markdown 转换 | ✅ | 发送前自动去除 markdown 格式以适配 QQ 纯文本 |
| SSRF 防护 | ✅ | 媒体下载时阻止重定向到内网地址 |
| 消息撤回 | ✅ | delete_message API |
| 定时任务投递 | ✅ | 通过 `napcat:<QQ号或群号>` 投递 |
| 跨平台发送 | ✅ | `send_message` 工具支持 napcat 平台 |
| 网关自动发现 | ✅ | 通过 `plugin.yaml` + `platform_registry` 注册，无需手动打补丁 |
| 消息编辑 | ❌ | OneBot 11 不支持 |
| 输入状态 | ❌ | OneBot 11 无标准实现 |

---

## 消息格式

适配器遵循 OneBot 11 消息段数组格式：

```json
[
  {"type": "reply", "data": {"id": "12345"}},
  {"type": "text", "data": {"text": "Hello "}},
  {"type": "image", "data": {"file": "https://example.com/img.png"}}
]
```

支持的消息段类型：`text`, `image`, `record`, `video`, `file`, `at`, `reply`, `face`, `forward`

---

## 连接机制

- **正向模式** (`NAPCAT_WS_MODE=forward`): 适配器作为 WS 客户端连接 NapCat 的 WS Server（`websocketServers`），指数退避重连
- **反向模式** (`NAPCAT_WS_MODE=reverse`): 适配器启动 WS Server，NapCat 作为 WS 客户端连接过来（`websocketClients`），断线后 NapCat 自动重连
- **重连策略**: 正向模式使用指数退避 + 随机抖动，退避序列 `[2, 5, 10, 30, 60]` 秒，最多 100 次尝试；反向模式由 NapCat 侧 `reconnectInterval` 控制
- **心跳**: 响应 NapCat 的 `meta_event.heartbeat` 事件
- **消息去重**: 基于 `message_id`，5 秒窗口内去重，最多缓存 1000 条
- **平台锁**: 同一 HTTP URL 只允许一个连接实例，防止重复连接
- **SSRF 防护**: HTTP 客户端注册了 `_ssrf_redirect_guard` 响应钩子，阻止媒体下载时重定向到内网地址
- **错误隔离**: 单条消息处理失败不会影响 WebSocket 监听器，自动记录日志并跳过

---

## 定时任务

通过 Hermes 的 cron 系统，可以将定时任务结果投递到 QQ：

```
deliver: napcat:123456789       # 投递到 QQ 号 123456789（私聊）
deliver: napcat:g:987654321     # 投递到群号 987654321（群聊）
```

设置 `NAPCAT_HOME_CHANNEL` 后可使用默认投递目标。

---

## 故障排查

### 诊断工具

项目内置了完整的运维工具链，位于 `scripts/` 目录：

| 脚本 | 用途 |
|------|------|
| `scripts/diagnose.sh` | 全量诊断 — 检查环境变量、Python 依赖、HTTP/WS 连通性、Hermes 集成 |
| `scripts/health-check.sh` | 快速健康检查 — 适合 cron / systemd timer，支持 `--json` 输出 |
| `scripts/logs-tail.sh` | 日志实时查看 — 自动定位日志文件，高亮 NapCat 相关行 |
| `scripts/quick-setup-env.sh` | 交互式 `.env` 配置 — 不依赖 `hermes gateway setup`，直接编辑环境变量 |
| `scripts/test-message.sh` | 消息发送测试 — 绕过 Hermes 直接调用 NapCat API |

```bash
# 快速诊断
bash scripts/diagnose.sh

# 健康检查（JSON 输出，适合监控）
bash scripts/health-check.sh --json

# 实时查看日志
bash scripts/logs-tail.sh -n 100 --grep napcat
```

### 常见问题

| 问题 | 排查方法 |
|------|----------|
| 连接失败 | 检查 `NAPCAT_HTTP_URL`/`NAPCAT_WS_URL` 是否正确，NapCat 是否正在运行。反向模式需确认 `NAPCAT_WS_MODE=reverse` |
| 反向模式连不上 | 确认 NapCat 配置的是 `websocketClients`（非 `websocketServers`），URL 指向适配器的 `NAPCAT_WS_URL`，且 `NAPCAT_WS_MODE=reverse` |
| 收不到消息 | 确认 NapCat 配置中 `messagePostFormat` 为 `"array"` |
| 发送失败 | 检查 HTTP API 是否可达：`curl http://127.0.0.1:3000/get_login_info` |
| Token 认证失败 | 确保 `.env` 中的 `NAPCAT_TOKEN` 与 NapCat 配置的 token 一致 |
| 权限被拒 | 检查 `NAPCAT_ALLOWED_USERS` 是否包含发送者 QQ 号，或设置 `NAPCAT_ALLOW_ALL_USERS=true` |
| 群聊无响应 | 默认需要 @机器人，可设 `NAPCAT_REQUIRE_MENTION=false` 关闭此限制 |
| 转发消息无内容 | 检查 NapCat HTTP API 是否正常（转发展开依赖 HTTP `/get_forward_msg`） |
| 管理员命令无效 | 确认 `NAPCAT_ADMIN_USERS` 包含你的 QQ 号，群聊中还需要同时 @机器人 |
| 机器人回复冗长 / 误调 send_message | 在 `config.yaml` 的 `system_prompt` 追加：*你是 QQ 里的聊天机器人。你发出的每条消息，就是你对用户的回复。规则：1. 群聊 @你 = 对你说话，直接回 2. 私聊 = 一对一聊天，直接回 3. 任何对话中，严禁调用 send_message 工具 4. 你的回复就是最终答案，没有"已发送""已完成"这些事* |

```bash
hermes status           # 查看 NapCat 平台配置状态
hermes status --deep    # 深度检查（含端口连通性）
hermes doctor           # 运行完整诊断
```

---

## 许可证

MIT License — 与 Hermes Agent 一致。
