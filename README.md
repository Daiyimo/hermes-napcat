# Hermes-NapCat Adapter

QQ 消息平台适配器，通过 [NapCat](https://napneko.github.io) 的 OneBot 11 协议接入 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 框架。

| 依赖 | 版本 |
|------|------|
| Hermes Agent | v0.11.0 |
| NapCat | v4.18.1+ |
| Python | >= 3.11 |

---

## 架构

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

- **事件流**: NapCat WS 推送 → 适配器解析 OneBot 11 事件 → 构建 `MessageEvent` → 调用 `handle_message()`
- **发送流**: 适配器构建 OneBot 11 消息段数组 → HTTP POST 到 NapCat `/send_msg`

---

## 文件结构

```
hermes-napcat/
├── __init__.py           # 包导出: NapCatAdapter, check_napcat_requirements
├── adapter.py            # 主适配器类 (BasePlatformAdapter 子类)
├── constants.py          # 协议常量、超时、API 端点
├── event_parser.py       # OneBot 11 事件 → MessageEvent 转换 + 转发消息展开
├── group_commands.py     # 群管理命令处理（/mute /kick /status /ping /help）
├── message_builder.py    # 文本/媒体 → OneBot 11 消息段数组构建
├── utils.py              # HTTP 客户端辅助、QQ 号脱敏
└── README.md
```

---

## 安装

### 1. 安装 Hermes Agent

如果尚未安装，先完成 Hermes Agent 安装：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

详见 [Hermes Agent 文档](https://hermes-agent.nousresearch.com/docs/)。

### 2. 安装适配器

```bash
# 克隆到 Hermes Agent 的平台目录（推荐）
cd /path/to/hermes-agent/gateway/platforms
git clone https://github.com/Daiyimo/hermes-napcat.git napcat
```

或者克隆到其他位置后创建符号链接：

```bash
git clone https://github.com/Daiyimo/hermes-napcat.git ~/hermes-napcat

# Linux / macOS
ln -s ~/hermes-napcat /path/to/hermes-agent/gateway/platforms/napcat

# Windows (管理员权限 CMD)
mklink /J C:\path\to\hermes-agent\gateway\platforms\napcat C:\path\to\hermes-napcat
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
  2. 登录 QQ 账号后，在 NapCat 网络配置中启用 HTTP Server（默认端口 3000）和 WebSocket Server（默认端口 3001）
  3. 将两个 Server 的 messagePostFormat 均设为 array
  4. 如需 Token 鉴权，在两个 Server 中填写相同的 token 字段

  NapCat HTTP Server 地址，例如 http://127.0.0.1:3000
  NapCat HTTP API 地址: http://127.0.0.1:3000

  NapCat WebSocket Server 地址，例如 ws://127.0.0.1:3001
  NapCat WebSocket 地址: ws://127.0.0.1:3001

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

安装并运行 [NapCat](https://napneko.github.io) v4.18.1+，登录 QQ 账号后，编辑 `onebot11_<QQ号>.json`，启用 **HTTP Server** 和 **WebSocket Server**：

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

> **重要**: `messagePostFormat` 必须设为 `"array"`，适配器依赖消息段数组格式。

---

## 环境变量参考

以下变量由 `hermes gateway setup` 自动配置，也可手动编辑 `.env`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `NAPCAT_HTTP_URL` | 是 | NapCat HTTP API 地址，如 `http://127.0.0.1:3000` |
| `NAPCAT_WS_URL` | 是 | NapCat WebSocket 地址，如 `ws://127.0.0.1:3001` |
| `NAPCAT_TOKEN` | 否 | NapCat 访问令牌（与 NapCat 配置中的 token 字段一致） |
| `NAPCAT_HOME_CHANNEL` | 否 | 默认投递目标（QQ 号或群号，用于定时任务投递） |
| `NAPCAT_ALLOWED_USERS` | 否 | 允许私聊的 QQ 号，逗号分隔（为空则不限制） |
| `NAPCAT_GROUP_ALLOWED_USERS` | 否 | 允许在群聊中使用的 QQ 号，逗号分隔 |
| `NAPCAT_ALLOW_ALL_USERS` | 否 | 设为 `true` 允许所有用户 |
| `NAPCAT_ADMIN_USERS` | 否 | 管理员 QQ 号，逗号分隔，允许执行 /mute /kick 等命令 |
| `NAPCAT_REQUIRE_MENTION` | 否 | 群聊是否需要 @机器人 才触发（默认 `true`） |
| `NAPCAT_ENABLE_REACTIONS` | 否 | 是否启用贴表情回应（默认 `true`） |

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
| 贴表情回应 | ✅ | 根据消息语义自动贴对应 QQ 表情（可通过 `NAPCAT_ENABLE_REACTIONS=false` 关闭） |
| 群管理命令 | ✅ | `/mute /ban /kick /status /ping /help`（需设置 `NAPCAT_ADMIN_USERS`） |
| 消息撤回 | ✅ | delete_message API |
| 消息编辑 | ❌ | OneBot 11 不支持 |
| 输入状态 | ❌ | OneBot 11 无标准实现 |
| 定时任务投递 | ✅ | 通过 `napcat:<QQ号或群号>` 投递 |
| 跨平台发送 | ✅ | `send_message` 工具支持 napcat 平台 |
| 用户鉴权 | ✅ | 基于 QQ 号白名单 |

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

- **WebSocket**: 适配器作为客户端连接 NapCat 的 WS Server（正向 WebSocket）
- **重连策略**: 指数退避 + 随机抖动，退避序列 `[2, 5, 10, 30, 60]` 秒，最多 100 次尝试
- **心跳**: 响应 NapCat 的 `meta_event.heartbeat` 事件
- **消息去重**: 基于 `message_id`，5 秒窗口内去重，最多缓存 1000 条

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

| 问题 | 排查方法 |
|------|----------|
| 连接失败 | 检查 `NAPCAT_HTTP_URL` 和 `NAPCAT_WS_URL` 是否正确，NapCat 是否正在运行 |
| 收不到消息 | 确认 NapCat 配置中 `messagePostFormat` 为 `"array"` |
| 发送失败 | 检查 HTTP API 是否可达：`curl http://127.0.0.1:3000/get_login_info` |
| Token 认证失败 | 确保 `.env` 中的 `NAPCAT_TOKEN` 与 NapCat 配置的 token 一致 |
| 权限被拒 | 检查 `NAPCAT_ALLOWED_USERS` 是否包含发送者 QQ 号，或设置 `NAPCAT_ALLOW_ALL_USERS=true` |
| 群聊无响应 | 默认需要 @机器人，可设 `NAPCAT_REQUIRE_MENTION=false` 关闭此限制 |
| 转发消息无内容 | 检查 NapCat HTTP API 是否正常（转发展开依赖 HTTP `/get_forward_msg`） |
| 管理员命令无效 | 确认 `NAPCAT_ADMIN_USERS` 包含你的 QQ 号，群聊中还需要同时 @机器人 |

```bash
hermes status           # 查看 NapCat 平台配置状态
hermes status --deep    # 深度检查（含端口连通性）
hermes doctor           # 运行完整诊断
```

---

## 许可证

MIT License — 与 Hermes Agent 一致。
