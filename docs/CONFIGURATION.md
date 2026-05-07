# NapCat 配置详解

本文档详细介绍 NapCat 侧和适配器侧的完整配置方法。

---

## 目录

- [正向 WebSocket 模式（推荐）](#正向-websocket-模式推荐默认)
- [反向 WebSocket 模式](#反向-websocket-模式)
- [环境变量参考](#环境变量参考)
- [连接机制](#连接机制)
- [定时任务投递](#定时任务投递)

---

## 正向 WebSocket 模式（推荐，默认）

正向模式：适配器作为 WS 客户端连接 NapCat 的 WS Server。

### NapCat 配置

编辑 `onebot11_<QQ号>.json`：

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

### 适配器配置

```bash
NAPCAT_HTTP_URL=http://127.0.0.1:3000
NAPCAT_WS_URL=ws://127.0.0.1:3001
NAPCAT_WS_MODE=forward
```

---

## 反向 WebSocket 模式

反向模式：适配器作为 WS Server，NapCat 作为 WS Client 连接过来。

### NapCat 配置

编辑 `onebot11_<QQ号>.json`：

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

### 适配器配置

```bash
NAPCAT_HTTP_URL=http://127.0.0.1:3000
NAPCAT_WS_URL=ws://127.0.0.1:3002
NAPCAT_WS_MODE=reverse
```

> ⚠️ **重要**: `messagePostFormat` 必须设为 `"array"`，适配器依赖消息段数组格式。

---

## 环境变量参考

以下变量由 `hermes gateway setup` 自动配置，也可手动编辑 `.env`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `NAPCAT_HTTP_URL` | 是 | NapCat HTTP API 地址，如 `http://127.0.0.1:3000` |
| `NAPCAT_WS_URL` | 是 | NapCat WebSocket 地址。<br>正向模式：NapCat WS 服务器地址，如 `ws://127.0.0.1:3001`<br>反向模式：适配器监听地址，如 `ws://127.0.0.1:3002` |
| `NAPCAT_WS_MODE` | 否 | WebSocket 模式：`forward`（默认）或 `reverse` |
| `NAPCAT_TOKEN` | 否 | NapCat 访问令牌（与 NapCat 配置的 token 一致） |
| `NAPCAT_HOME_CHANNEL` | 否 | 默认投递目标（QQ 号或群号，用于定时任务） |
| `NAPCAT_ALLOWED_USERS` | 否 | 允许私聊的 QQ 号，逗号分隔（留空则不限制） |
| `NAPCAT_GROUP_ALLOWED_USERS` | 否 | 群聊中允许触发的 QQ 号，逗号分隔（优先级高于全局名单） |
| `NAPCAT_ALLOW_ALL_USERS` | 否 | 设为 `true` 允许所有用户 |
| `NAPCAT_ADMIN_USERS` | 否 | 管理员 QQ 号，逗号分隔，允许执行 `/mute /kick` 等命令 |
| `NAPCAT_REQUIRE_MENTION` | 否 | 群聊是否需要 @机器人 才触发（默认 `true`） |
| `NAPCAT_ENABLE_REACTIONS` | 否 | 是否启用处理状态贴表情（思考 → 👍/😡，默认 `true`） |
| `NAPCAT_REPLY_MODE` | 否 | 回复引用模式：`off` 不引用（默认），`first` 仅首段引用，`all` 全部引用 |

---

## 连接机制

### 重连策略

- **正向模式**: 指数退避 + 随机抖动
  - 退避序列: `[2, 5, 10, 30, 60]` 秒
  - 最多 100 次尝试
  - 每次退避增加 ±50% 随机抖动

- **反向模式**: 由 NapCat 侧 `reconnectInterval` 控制（默认 5000ms）

### 心跳

适配器响应 NapCat 的 `meta_event.heartbeat` 事件，维持连接活跃。

### 消息去重

基于 `message_id`，5 秒窗口内去重，最多缓存 1000 条。

### 平台锁

同一 HTTP URL 只允许一个连接实例，防止重复连接。

### SSRF 防护

HTTP 客户端注册了 `_ssrf_redirect_guard` 响应钩子，阻止媒体下载时重定向到内网地址。

---

## 定时任务投递

通过 Hermes 的 cron 系统，将定时任务结果投递到 QQ：

```yaml
# 投递到私聊
deliver: napcat:123456789

# 投递到群聊
deliver: napcat:g:987654321
```

设置 `NAPCAT_HOME_CHANNEL` 后可使用默认投递目标。

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
      - "3000:3000"    # HTTP API — Hermes 需要调用
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

NapCat 侧配 `websocketServers` 开 3001，Hermes 侧用容器名 `napcat` 作为主机名直连。
