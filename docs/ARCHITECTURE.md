# 项目架构

本文档描述 hermes-napcat 的代码架构和设计决策。

---

## 总体架构

```
用户消息 → NapCat (OneBot 11) → WS/HTTP → 适配器 → Hermes Gateway → Agent
```

适配器作为 Hermes Gateway 和 NapCat 之间的桥梁，实现 OneBot 11 协议的双向转换。

---

## 核心模块

### 1. `adapter.py` — 主适配器 (~1100 行)

`NapCatAdapter` 类，继承自 `BasePlatformAdapter`，是整个项目的核心。

**职责：**
- WebSocket 连接管理（正向/反向模式）
- HTTP API 客户端（发送消息、调用 NapCat API）
- 消息事件接收与分发
- 平台注册（通过 `plugin.yaml` + `platform_registry`）

**关键方法：**
- `connect()` — 建立 WS 连接（正向模式指数退避重连）
- `_ws_listener()` — 持续监听 NapCat 事件
- `handle_message()` — 处理消息事件（白名单检查、表情反应、分发）
- `send_message()` — 构建并发送 OneBot 11 消息段数组
- `_call_napcat_api()` — 统一的 HTTP API 调用封装

**设计要点：**
- 使用 `asyncio` 实现异步 I/O
- 连接池复用 `httpx.AsyncClient`
- 消息去重基于 `message_id`（5 秒窗口，最多 1000 条）
- 单 HTTP URL 只允许一个连接实例（平台锁）

---

### 2. `event_parser.py` — 事件解析 (~500 行)

将 OneBot 11 事件转换为 Hermes `MessageEvent`。

**支持的 post_type：**
- `message` / `message_sent` → 消息事件
- `meta_event` → 心跳、生命周期事件
- `notice` → 群管理通知（忽略）
- `request` → 好友/群请求（忽略）

**核心功能：**
- 消息段数组 → `MessageEvent` 转换
- 合并转发消息展开（调用 `/get_forward_msg`，最多 10 条，每条约 200 字符）
- QQ 表情映射（102 个内置表情 → Unicode emoji）
- @ 提及解析为 `@昵称` 文本

---

### 3. `message_builder.py` — 消息构建 (~180 行)

将 Hermes 消息转换为 OneBot 11 消息段数组。

**支持的消息段类型：**
- `text` — 纯文本（自动去除 Markdown）
- `image` — 图片（URL 或本地文件路径）
- `record` — 语音消息
- `video` — 视频消息
- `file` — 文件传输
- `at` — @提及
- `reply` — 引用回复
- `forward` — 合并转发

**特殊处理：**
- 超长消息自动分块（>4500 字符，块间限速 300ms）
- 文本消息去除 Markdown 格式（适配 QQ 纯文本）
- 本地媒体文件自动上传到 NapCat

---

### 4. `constants.py` — 协议常量 (~230 行)

集中管理所有配置参数和协议常量。

**分类：**
- 消息限制（`MAX_MESSAGE_LENGTH = 4500`）
- WebSocket 配置（超时、ping 间隔）
- HTTP API 超时（一般 15s，媒体下载 60s）
- 重连策略（指数退避：[2, 5, 10, 30, 60] 秒，最多 100 次）
- OneBot 11 协议常量（post_type、message_type、消息段类型）
- NapCat API 端点（60+ 个 API）
- 表情反应 ID（思考=32，成功=76，失败=326）
- 熔断器参数（失败阈值 5，打开超时 30s，半开探测 1 次）
- 告警引擎参数（滑动窗口 60s，错误阈值 10 次）

---

### 5. `group_commands.py` — 群管理命令 (~370 行)

实现 QQ 群管理命令，仅管理员可用。

**支持的命令：**
- `/mute` — 禁言（支持分钟数和永久禁言）
- `/ban` — 踢出群聊
- `/status` — 查看机器人状态
- `/ping` — 延迟测试
- `/help` — 命令帮助

**权限控制：**
- 检查 `NAPCAT_ADMIN_USERS` 环境变量
- 管理员自动绕过白名单检查

---

### 6. `observability.py` — 可观测性 (~460 行)

实现指标收集、熔断器和告警引擎。

**组件：**

#### a. 指标收集
- 消息收发延迟（RingBuffer 缓存最近 50 个样本）
- 消息数量计数（接收/发送/失败）
- 错误发生次数

#### b. 熔断器（Circuit Breaker）
状态机：`CLOSED → OPEN → HALF_OPEN → CLOSED`

- **CLOSED**: 正常状态，记录失败次数
- **OPEN**: 连续失败超过阈值（5次）后进入，快速失败，不发送请求
- **HALF_OPEN**: 30 秒后允许 1 次探测请求，成功则恢复 CLOSED

#### c. 告警引擎
滑动窗口统计（60 秒），支持 4 种告警规则：

| 规则 | 触发条件 | 冷却时间 |
|------|----------|---------|
| `error_spike` | 60 秒内错误 ≥ 10 次 | 120 秒 |
| `ws_reconnect_burst` | 60 秒内重连 ≥ 5 次 | 120 秒 |
| `send_failure_rate` | 发送失败率 ≥ 50% | 120 秒 |
| `no_heartbeat` | 90 秒未收到心跳 | 60 秒 |

告警级别：`INFO` / `WARNING` / `CRITICAL`

---

### 7. `utils.py` — 工具函数 (~120 行)

- `get_http_client()` — 创建配置好的 `httpx.AsyncClient`（含 SSRF 防护钩子）
- `mask_qq()` — QQ 号脱敏（如 `123456789` → `123***789`）
- `get_message_id()` — 从 OneBot 11 事件提取消息 ID

---

## 数据流

### 接收消息

```
NapCat WS → adapter._ws_listener()
  → event_parser.parse_message()
    → adapter.handle_message()
      → 白名单检查
      → 表情反应（🤫）
      → gateway.handle_message(event)
      → 表情替换（👍/😡）
```

### 发送消息

```
gateway.send_message()
  → adapter.send_message()
    → message_builder.build_message_segments()
      → 文本/Markdown 转换
      → 媒体上传（本地文件 → NapCat）
      → 消息分块（>4500 字符）
    → adapter._call_napcat_api("/send_msg")
      → 熔断器检查
      → HTTP POST
      → 指标记录
```

---

## 配置管理

环境变量由 Hermes Gateway 统一管理，适配器通过 `os.getenv()` 读取：

- **必填**: `NAPCAT_HTTP_URL`, `NAPCAT_WS_URL`
- **可选**: `NAPCAT_TOKEN`, `NAPCAT_ALLOWED_USERS`, `NAPCAT_ADMIN_USERS` 等

配置变更需重启 Gateway 生效。

---

## 测试架构

所有测试在 `tests/` 目录，使用 `pytest` + `pytest-asyncio`。

**测试隔离策略：**
- `tests/conftest.py` 提供完整的 stub 实现：
  - `StubWebSocket` — 模拟 WS 连接
  - `StubHTTPClient` — 模拟 HTTP API 响应
  - `StubGateway` — 模拟 Hermes Gateway
- 不依赖真实 NapCat 或 Hermes Gateway

**测试覆盖：**
- `test_adapter_logic.py` — 连接逻辑、消息处理流程
- `test_event_parser.py` — 事件解析、表情映射、转发展开
- `test_group_commands.py` — 群管理命令、权限检查
- `test_message_builder.py` — 消息构建、分块、媒体处理
- `test_observability.py` — 指标、熔断器、告警引擎
- `test_utils.py` — 工具函数

---

## 扩展点

如需添加新功能，关注以下接口：

1. **新消息段类型**: 修改 `message_builder.py` 的 `build_message_segments()`
2. **新 API 端点**: 在 `constants.py` 添加 `API_*` 常量，在 `adapter.py` 添加调用方法
3. **新群命令**: 在 `group_commands.py` 的 `COMMANDS` 字典注册
4. **新告警规则**: 在 `observability.py` 的 `_alert_loop()` 添加规则
