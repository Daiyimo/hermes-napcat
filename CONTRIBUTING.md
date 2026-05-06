# Contributing to hermes-napcat

感谢你的贡献！以下是开发、测试和提交的完整指南。

---

## 目录

1. [开发环境搭建](#开发环境搭建)
2. [运行测试](#运行测试)
3. [代码规范](#代码规范)
4. [项目结构](#项目结构)
5. [提交规范](#提交规范)
6. [Pull Request 流程](#pull-request-流程)
7. [常见问题](#常见问题)

---

## 开发环境搭建

### 前置要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.11 | 运行时 |
| git | 任意 | 版本管理 |
| NapCat | v4.18.1+ | 本地测试（可选） |

### 克隆与初始化

```bash
git clone https://github.com/Daiyimo/hermes-napcat.git
cd hermes-napcat

# 安装所有开发依赖（含测试、格式化、pre-commit）
pip install -r requirements.txt

# 安装 git pre-commit 钩子（首次克隆后执行一次即可）
pre-commit install
```

> 不需要安装完整的 Hermes Agent。项目测试通过 `conftest.py` 中的 gateway stub 隔离所有 gateway 依赖，可独立运行。

---

## Pre-commit 钩子

每次 `git commit` 时自动执行三项检查，与 CI 保持一致：

| 钩子 | 作用 |
|------|------|
| `ruff (lint)` | 检查代码错误、未使用导入、风格问题 |
| `ruff (format)` | 检查代码格式是否统一（不自动修改，需手动运行 `ruff format .`） |
| `pytest` | 运行全部单元测试，**测试失败则拒绝提交** |

```bash
# 手动对所有文件运行全部钩子（等价于 CI 检查）
pre-commit run --all-files

# 只运行某一项
pre-commit run ruff-lint --all-files
pre-commit run pytest --all-files

# 修复 ruff 可自动修复的问题
ruff check --fix .

# 格式化所有文件
ruff format .

# 跳过钩子提交（紧急情况，不推荐）
git commit --no-verify -m "message"
```

---

## 运行测试

所有测试位于 `tests/` 目录，使用 `pytest` + `pytest-asyncio`。

```bash
# 进入测试目录（pytest.ini 在此）
cd tests

# 运行全部测试
python -m pytest . -v

# 只运行某个模块
python -m pytest test_utils.py -v
python -m pytest test_message_builder.py -v
python -m pytest test_event_parser.py -v
python -m pytest test_group_commands.py -v

# 运行带覆盖率报告
pip install pytest-cov
python -m pytest . -v --cov=.. --cov-report=term-missing

# 运行单个测试
python -m pytest test_utils.py::TestOneBotAPIError::test_str_uses_wording -v
```

预期结果：**99 passed, 2 skipped**（2 个 Unix-only 的文件 URI 测试在 Windows 上跳过）。

### 测试结构

| 文件 | 覆盖模块 | 测试数 |
|------|---------|--------|
| `test_utils.py` | `utils.py` | 14 |
| `test_message_builder.py` | `message_builder.py` | 22 |
| `test_event_parser.py` | `event_parser.py` | 27 |
| `test_group_commands.py` | `group_commands.py` | 38 |

### 新增测试

1. 在对应的 `tests/test_<module>.py` 文件中追加测试类或函数
2. 异步测试用 `@pytest.mark.asyncio` 装饰（`pytest.ini` 已配置 `asyncio_mode = auto`，也可省略）
3. Mock 网络请求用 `unittest.mock.AsyncMock`，不要发真实网络请求
4. 参考 `tests/conftest.py` 了解 gateway stub 机制

---

## 代码规范

### Python 版本与风格

- 目标 Python **3.11+**，可使用 `match`、`tomllib`、`Self` 等新特性
- 遵循 **PEP 8**，行宽上限 **100** 字符
- 所有公共函数、方法、类必须有 **docstring**，格式参见下方
- 所有函数参数和返回值必须有 **类型注解**

### Docstring 格式

使用 **Google 风格**：

```python
def example(param1: str, param2: int = 0) -> Optional[str]:
    """单行摘要，不超过 79 字符。

    可选的多行详细说明。说明设计决策、边界条件、
    或与外部协议的关联。

    Args:
        param1: 参数说明。
        param2: 参数说明，含默认值语义。

    Returns:
        返回值说明。为 ``None`` 时的条件也要写清楚。

    Raises:
        ValueError: 说明何时抛出。
        OneBotAPIError: 说明何时抛出。
    """
```

私有函数（`_` 前缀）可以只写单行摘要。

### 异常处理规范

- **不要**裸 `except:` 或无日志的 `except Exception: pass`
- 捕获具体异常类型（`httpx.HTTPError`、`asyncio.TimeoutError` 等）优先于 `Exception`
- 意料外的 `except Exception` 必须用 `logger.error(..., exc_info=True)` 记录完整堆栈
- 已知的、可降级的失败用 `logger.warning`

### 常量管理

- 所有魔法数字和字符串必须定义在 `constants.py`
- 常量命名全大写 + 下划线，并附注释说明来源或含义

### 导入顺序

```python
# 1. __future__
from __future__ import annotations

# 2. 标准库
import asyncio
import json

# 3. 第三方库
import httpx
import websockets

# 4. 本地相对导入
from .constants import API_TIMEOUT
from .utils import OneBotAPIError
```

---

## 项目结构

```
hermes-napcat/
├── adapter.py          # 主适配器：连接管理、事件分发、消息收发
├── constants.py        # 全局常量：协议值、超时、端点、emoji ID
├── event_parser.py     # 入站事件解析：OneBot 11 → MessageEvent
├── group_commands.py   # 群管理命令：/mute /kick /status /ping /help
├── message_builder.py  # 出站消息构建：文本/媒体 → OneBot 11 段数组
├── utils.py            # 工具函数：HTTP API 调用、日志脱敏
├── __init__.py         # 包导出 + platform_registry 自动注册
├── plugin.yaml         # 网关自动发现清单
├── requirements.txt    # 依赖声明（含测试依赖）
│
├── tests/              # 单元测试
│   ├── conftest.py         # Gateway stub + napcat 包别名
│   ├── pytest.ini          # asyncio_mode=auto, --import-mode=importlib
│   ├── test_utils.py
│   ├── test_message_builder.py
│   ├── test_event_parser.py
│   └── test_group_commands.py
│
├── scripts/            # 运维脚本
│   ├── install.sh          # 安装 + 平台注册修补
│   ├── diagnose.sh         # 全量环境诊断
│   ├── health-check.sh     # 快速健康检查（支持 --json）
│   ├── logs-tail.sh        # 日志实时查看
│   ├── quick-setup-env.sh  # 交互式 .env 配置
│   └── test-message.sh     # 直接 API 测试
│
├── CHANGELOG.md
├── CONTRIBUTING.md     # 本文件
└── README.md
```

### 模块职责边界

| 模块 | 职责 | 禁止 |
|------|------|------|
| `adapter.py` | 连接、分发、授权、发送 | 直接拼 OneBot 11 消息段 |
| `event_parser.py` | 解析入站事件 | 网络请求（除通过 api_call） |
| `message_builder.py` | 构建出站消息段 | 网络请求、日志输出 |
| `group_commands.py` | 命令解析与执行 | 直接操作 WebSocket |
| `utils.py` | HTTP 辅助、日志 | 业务逻辑 |
| `constants.py` | 常量定义 | 任何逻辑 |

---

## 提交规范

遵循 **Conventional Commits**：

```
<type>(<scope>): <subject>

[可选 body]

[可选 footer]
```

| Type | 含义 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 仅文档变更 |
| `test` | 测试相关 |
| `refactor` | 重构（非 feat / fix） |
| `perf` | 性能优化 |
| `chore` | 构建、依赖等杂项 |

示例：
```
fix(utils): use `or` instead of `and` in API error detection

api_call raised OneBotAPIError only when BOTH retcode != 0 AND
status != "ok". A response with retcode=100 but status="ok" was
silently accepted as success. The condition is now an `or`.
```

---

## Pull Request 流程

1. **Fork** 仓库，基于 `master` 新建分支：
   ```bash
   git checkout -b fix/your-fix-name
   ```

2. **写代码** — 遵循上方规范

3. **补测试** — 新功能必须附带测试，Bug 修复必须附带回归测试

4. **确认测试通过**：
   ```bash
   cd tests && python -m pytest . -v
   # 预期：99 passed, 2 skipped
   ```

5. **提交**：使用 Conventional Commits 格式

6. **发起 PR**：
   - 标题与 commit 格式一致
   - 描述中说明：改了什么、为什么改、如何测试

7. **代码审查**：响应 review 意见，force-push 到同一分支

---

## 常见问题

**Q: 运行测试时提示 `ModuleNotFoundError: No module named 'gateway'`？**

A: 这是正常的 — 测试从 `tests/` 目录运行，`conftest.py` 会自动 stub 所有 gateway 依赖。确保从 `tests/` 目录执行 `python -m pytest .`，不要从项目根目录执行。

**Q: 如何在没有真实 NapCat 的情况下测试适配器逻辑？**

A: 使用 `unittest.mock.AsyncMock` mock `httpx.AsyncClient` 和 WebSocket 对象。参考 `tests/test_group_commands.py` 中的 `_ctx()` 工厂函数和 `monkeypatch.setattr(_gc, "api_call", ...)` 用法。

**Q: 新增一个 OneBot 11 消息段类型应该改哪些文件？**

A: 共三处：
1. `constants.py` — 添加 `SEG_XXX` 常量
2. `event_parser.py` — 在 `parse_message_segments()` 的 `for` 循环中添加处理分支
3. `message_builder.py` — 添加对应的段工厂函数（`xxx_segment()`）和高级构建函数
4. （可选）`tests/test_event_parser.py` + `tests/test_message_builder.py` — 补充测试

**Q: 如何添加一条新的群管理命令？**

A: 在 `group_commands.py` 的 `handle_group_command()` 函数中添加新的 `if cmd == "/xxx":` 分支，然后在 `/help` 的帮助文本和 `tests/test_group_commands.py` 中补充对应内容。
