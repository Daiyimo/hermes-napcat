# 文档索引

本文档汇总 hermes-napcat 项目的所有文档资源。

---

## 快速导航

| 需求 | 文档 |
|------|------|
| 🚀 快速开始 | [README.md](../README.md) |
| 📝 完整配置指南 | [docs/CONFIGURATION.md](CONFIGURATION.md) |
| 🔧 故障排查 | [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 🏗️ 架构设计 | [docs/ARCHITECTURE.md](ARCHITECTURE.md) |
| 📋 贡献指南 | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 📜 变更日志 | [CHANGELOG.md](../CHANGELOG.md) |

---

## 按角色分类

### 用户

- **安装部署**：README.md → 快速开始
- **配置参考**：docs/CONFIGURATION.md
- **问题排查**：docs/TROUBLESHOOTING.md

### 开发者

- **贡献流程**：CONTRIBUTING.md
- **架构理解**：docs/ARCHITECTURE.md
- **测试运行**：README.md → 开发与测试

---

## 配置示例

所有配置模板位于 `config/` 目录：

| 文件 | 用途 |
|------|------|
| `config/.env.example` | 环境变量配置（完整注释） |
| `config/napcat-forward.json.example` | NapCat 正向模式配置 |
| `config/napcat-reverse.json.example` | NapCat 反向模式配置 |
| `config/docker-compose.yml.example` | Docker Compose 部署示例 |
| `config/napcat-gateway.patch` | Hermes Gateway 补丁（自动安装脚本使用） |

---

## 运维脚本

所有运维工具位于 `scripts/` 目录：

| 脚本 | 用途 |
|------|------|
| `scripts/install.sh` | 一键安装（自动克隆 + 修补 + 注册） |
| `scripts/diagnose.sh` | 全量诊断 |
| `scripts/health-check.sh` | 快速健康检查 |
| `scripts/logs-tail.sh` | 日志查看 |
| `scripts/quick-setup-env.sh` | 交互式 .env 配置 |
| `scripts/test-message.sh` | API 消息测试 |

---

## 外部资源

- **NapCat 官方文档**：https://napneko.github.io
- **Hermes Agent 文档**：https://hermes-agent.nousresearch.com/docs/
- **OneBot 11 协议**：https://github.com/botuniverse/onebot-11
