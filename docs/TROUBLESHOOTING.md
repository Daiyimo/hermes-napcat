# 故障排查

本文档汇总常见问题及排查方法。

---

## 诊断工具

项目内置完整的运维工具链，位于 `scripts/` 目录：

| 脚本 | 用途 |
|------|------|
| `scripts/diagnose.sh` | 全量诊断 — 检查环境变量、Python 依赖、HTTP/WS 连通性、Hermes 集成 |
| `scripts/health-check.sh` | 快速健康检查 — 适合 cron / systemd timer，支持 `--json` 输出 |
| `scripts/logs-tail.sh` | 日志实时查看 — 自动定位日志文件，高亮 NapCat 相关行 |
| `scripts/quick-setup-env.sh` | 交互式 `.env` 配置 — 不依赖 `hermes gateway setup` |
| `scripts/test-message.sh` | 消息发送测试 — 绕过 Hermes 直接调用 NapCat API |

```bash
# 快速诊断
bash scripts/diagnose.sh

# 健康检查（JSON 输出，适合监控）
bash scripts/health-check.sh --json

# 实时查看日志
bash scripts/logs-tail.sh -n 100 --grep napcat
```

---

## 常见问题

| 问题 | 排查方法 |
|------|----------|
| **连接失败** | 检查 `NAPCAT_HTTP_URL`/`NAPCAT_WS_URL` 是否正确，NapCat 是否正在运行。反向模式需确认 `NAPCAT_WS_MODE=reverse` |
| **反向模式连不上** | 确认 NapCat 配置的是 `websocketClients`（非 `websocketServers`），URL 指向适配器的 `NAPCAT_WS_URL`，且 `NAPCAT_WS_MODE=reverse` |
| **收不到消息** | 确认 NapCat 配置中 `messagePostFormat` 为 `"array"` |
| **发送失败** | 检查 HTTP API 是否可达：`curl http://127.0.0.1:3000/get_login_info` |
| **Token 认证失败** | 确保 `.env` 中的 `NAPCAT_TOKEN` 与 NapCat 配置的 token 一致 |
| **权限被拒** | 检查 `NAPCAT_ALLOWED_USERS` 是否包含发送者 QQ 号，或设置 `NAPCAT_ALLOW_ALL_USERS=true` |
| **群聊无响应** | 默认需要 @机器人，可设 `NAPCAT_REQUIRE_MENTION=false` 关闭此限制 |
| **转发消息无内容** | 检查 NapCat HTTP API 是否正常（转发展开依赖 HTTP `/get_forward_msg`） |
| **管理员命令无效** | 确认 `NAPCAT_ADMIN_USERS` 包含你的 QQ 号，群聊中还需要同时 @机器人 |
| **机器人回复冗长 / 误调 send_message** | 在 `config.yaml` 的 `system_prompt` 追加：<br>*"你是 QQ 里的聊天机器人。你发出的每条消息，就是你对用户的回复。规则：1. 群聊 @你 = 对你说话，直接回 2. 私聊 = 一对一聊天，直接回 3. 任何对话中，严禁调用 send_message 工具 4. 你的回复就是最终答案，没有'已发送''已完成'这些事"* |

---

## Hermes 状态检查

```bash
hermes status           # 查看 NapCat 平台配置状态
hermes status --deep    # 深度检查（含端口连通性）
hermes doctor           # 运行完整诊断
```

---

## 安装后必须重启

如果 `hermes gateway` 已在运行，安装适配器后**必须重启**使平台注册生效，否则会报 `KeyError: 'napcat'`：

```bash
hermes gateway restart
```

---

## 日志查看

适配器日志由 Hermes Gateway 统一管理：

```bash
# 实时查看（前台运行）
hermes gateway

# 后台运行查看日志
journalctl -u hermes-gateway -f    # systemd
tail -f /var/log/hermes/gateway.log  # 日志文件
```

使用 `scripts/logs-tail.sh` 可自动定位日志文件并高亮 NapCat 相关行：

```bash
bash scripts/logs-tail.sh -n 100 --grep napcat
```
