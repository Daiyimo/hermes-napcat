#!/usr/bin/env bash
# ============================================================================
# Hermes-NapCat Adapter Installer
# ============================================================================
# Installs the NapCat (QQ) platform adapter into an existing Hermes Agent
# installation.  Clones the adapter repo into gateway/platforms/napcat/
# and patches hermes_cli/gateway.py to add the NapCat setup wizard.
# Also patches platforms.py, send_message_tool.py, and config.yaml to
# register napcat across all Hermes platform registration points.
#
# The adapter uses plugin.yaml + platform_registry for runtime auto-discovery
# (no manual patching needed for the gateway to find NapCat).  The gateway.py
# patch here only adds the interactive "hermes gateway setup" wizard entry.
#
# Usage:
#   bash scripts/install.sh                # Auto-detect hermes install dir
#   bash scripts/install.sh /opt/hermes    # Specify hermes install dir
#   bash scripts/install.sh --help         # Show help
#
# One-liner (from GitHub):
#   curl -fsSL https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/scripts/install.sh | bash
# ============================================================================

set -e

# ── Colors ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[hermes-napcat]${NC} $*"; }
success() { echo -e "${GREEN}[hermes-napcat]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[hermes-napcat]${NC} ! $*"; }
error()   { echo -e "${RED}[hermes-napcat]${NC} ✗ $*" >&2; exit 1; }

# ── Configuration ───────────────────────────────────────────────
REPO_URL="https://github.com/Daiyimo/hermes-napcat.git"
PROXY_REPO_URL="https://gh-proxy.com/https://github.com/Daiyimo/hermes-napcat.git"

# ── Interactive detection ───────────────────────────────────────
if [ -t 0 ]; then
    IS_INTERACTIVE=true
else
    IS_INTERACTIVE=false
fi

# ── Help ────────────────────────────────────────────────────────
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    echo "Hermes-NapCat Adapter Installer"
    echo ""
    echo "Usage: install.sh [DIRECTORY]"
    echo ""
    echo "  DIRECTORY    Path to hermes installation (optional, auto-detected)"
    echo "  -h, --help   Show this help"
    echo ""
    echo "The script clones the NapCat adapter into the hermes platforms"
    echo "directory and patches gateway.py to add the NapCat setup wizard."
    echo ""
    echo "Hermes Agent must already be installed before running this script."
    exit 0
fi

# ── Prerequisite checks ─────────────────────────────────────────
# Detect Python (try python3, then python, then python3.11)
detect_python() {
    for cmd in python3 python python3.12 python3.11 python3.10; do
        if command -v "$cmd" >/dev/null 2>&1; then
            PYTHON_BIN="$cmd"
            return 0
        fi
    done
    error "未找到 Python（尝试过：python3, python, python3.12, python3.11, python3.10）"
    info "请安装 Python >= 3.10 后重试"
    exit 1
}

detect_git() {
    if command -v git >/dev/null 2>&1; then
        return 0
    fi
    error "未找到 Git，请安装后重试"
}

info "检查前置依赖..."
detect_python
success "Python: $($PYTHON_BIN --version 2>&1)"
detect_git
success "Git: $(git --version | awk '{print $3}')"

# ── Check Python dependencies ──────────────────────────────────────
check_python_deps() {
    local missing=()

    for dep in websockets httpx; do
        if ! "$PYTHON_BIN" -c "import ${dep//-/_}" 2>/dev/null; then
            missing+=("$dep")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        warn "缺少 Python 依赖：${missing[*]}"
        info "尝试自动安装..."

        # Try pip install
        if "$PYTHON_BIN" -m pip install --quiet "${missing[@]}" 2>/dev/null; then
            success "依赖安装成功：${missing[*]}"
        else
            error "自动安装失败，请手动运行：\n  $PYTHON_BIN -m pip install ${missing[*]}"
        fi
    else
        success "Python 依赖检查通过（websockets, httpx）"
    fi
}

# Only check deps after finding hermes home (to use correct Python env)
# We'll call this after HERMES_HOME is detected

# ── Locate hermes installation ──────────────────────────────────
find_hermes_home() {
    local explicit="${1:-}"

    # Explicit path from CLI arg
    if [ -n "$explicit" ]; then
        if [ -f "$explicit/hermes_cli/gateway.py" ]; then
            echo "$explicit"; return
        fi
        error "指定目录中未找到 hermes_cli/gateway.py: $explicit"
    fi

    # Common install locations
    for candidate in \
        /opt/hermes \
        /opt/hermes-agent \
        "$HOME/.hermes" \
        "$HOME/hermes-agent" \
        /usr/local/lib/hermes-agent; do
        if [ -f "$candidate/hermes_cli/gateway.py" ]; then
            echo "$candidate"; return
        fi
    done

    # Try Python import resolution
    local found
    found=$("$PYTHON_BIN" -c "
import importlib.util, os
spec = importlib.util.find_spec('hermes_cli')
if spec and spec.origin:
    d = os.path.dirname(os.path.dirname(spec.origin))
    candidate = os.path.join(d, 'hermes_cli', 'gateway.py')
    if os.path.isfile(candidate):
        print(d)
" 2>/dev/null) || true

    if [ -n "$found" ] && [ -f "$found/hermes_cli/gateway.py" ]; then
        echo "$found"; return
    fi

    echo ""
}

HERMES_HOME=$(find_hermes_home "${1:-}")
if [ -z "$HERMES_HOME" ]; then
    error "找不到 hermes 安装目录"
    echo ""
    echo "  请确认 Hermes Agent 已安装，或手动指定目录："
    echo "    bash scripts/install.sh /opt/hermes"
    echo ""
    echo "  如果尚未安装 Hermes Agent，请先运行："
    echo "    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    exit 1
fi
info "hermes 安装目录：$HERMES_HOME"

# ── Check Python dependencies ──────────────────────────────────────
info "检查 Python 依赖..."
check_python_deps

PLATFORMS_DIR="$HERMES_HOME/gateway/platforms"
GATEWAY_PY="$HERMES_HOME/hermes_cli/gateway.py"

if [ ! -d "$PLATFORMS_DIR" ]; then
    error "platforms 目录不存在：$PLATFORMS_DIR"
    info "请确认 Hermes Agent 版本 >= v0.11.0"
    exit 1
fi

if [ ! -f "$GATEWAY_PY" ]; then
    error "gateway.py 不存在：$GATEWAY_PY"
    info "该路径可能不是有效的 Hermes Agent 安装目录"
    exit 1
fi

# ── Step 1: Clone/update adapter ────────────────────────────────
NAPCAT_DIR="$PLATFORMS_DIR/napcat"
info "Step 1/3  安装适配器 → $NAPCAT_DIR"

if [ -d "$NAPCAT_DIR/.git" ]; then
    info "  已有仓库，执行 git pull 更新..."
    if git -C "$NAPCAT_DIR" pull --ff-only 2>/dev/null; then
        success "适配器已更新"
    else
        warn "git pull 失败，继续使用当前版本"
    fi
elif [ -d "$NAPCAT_DIR" ] && [ "$(ls -A "$NAPCAT_DIR" 2>/dev/null)" ]; then
    warn "$NAPCAT_DIR 已存在且非 git 仓库，跳过克隆"
else
    info "  克隆仓库..."
    if git clone --depth=1 "$REPO_URL" "$NAPCAT_DIR" 2>/dev/null; then
        success "克隆成功"
    else
        warn "直连 GitHub 失败，尝试 gh-proxy 代理..."
        git clone --depth=1 "$PROXY_REPO_URL" "$NAPCAT_DIR" \
            || error "克隆失败，请检查网络连接"
        success "通过代理克隆成功"
    fi
fi

# ── Step 2: Patch gateway.py ────────────────────────────────────
info "Step 2/3  修补 hermes_cli/gateway.py（添加 NapCat 配置向导）"

# Always take a backup before patching (idempotent: overwrites previous backup)
cp "$GATEWAY_PY" "${GATEWAY_PY}.bak"
info "  已备份 → ${GATEWAY_PY}.bak"

"$PYTHON_BIN" - "$GATEWAY_PY" "$NAPCAT_DIR" <<'PYEOF'
import sys, os, re

gateway_py = sys.argv[1]
napcat_dir = sys.argv[2]

content = open(gateway_py, encoding='utf-8').read()
original = content  # keep for dirty-check

# ════════════════════════════════════════════════════════════════
# Insert 1: napcat entry into _PLATFORMS list
#   Idempotency: check only for this specific block, NOT a broad
#   '"key": "napcat"' grep that would skip all three sub-patches.
# ════════════════════════════════════════════════════════════════
NAPCAT_PLATFORMS_MARKER = '"key": "napcat"'

napcat_platform_entry = r'''    {
        "key": "napcat",
        "label": "NapCat (QQ)",
        "emoji": "🐧",
        "token_var": "NAPCAT_HTTP_URL",
        "setup_instructions": [
            "1. 安装并运行 NapCat v4.18.1+（https://napneko.github.io）",
            "2. 登录 QQ 账号，在 NapCat 网络配置中启用 HTTP Server（默认端口 3000）",
            "3. 正向模式：启用 WebSocket Server（默认端口 3001）",
            "   反向模式：启用 WebSocket Client（填写适配器地址 ws://127.0.0.1:3002）",
            "4. 将 messagePostFormat 均设为 array",
            "5. 如需 Token 鉴权，在 Server/Client 中填写相同的 token 字段",
        ],
        "vars": [
            {"name": "NAPCAT_HTTP_URL", "prompt": "NapCat HTTP API 地址", "password": False,
             "help": "NapCat HTTP Server 地址，例如 http://127.0.0.1:3000"},
            {"name": "NAPCAT_WS_URL", "prompt": "NapCat WebSocket 地址", "password": False,
             "help": "正向填 WS Server 地址(如 ws://127.0.0.1:3001)，反向填适配器监听地址(如 ws://127.0.0.1:3002)"},
            {"name": "NAPCAT_WS_MODE", "prompt": "WS 模式 (forward=适配器连NapCat, reverse=NapCat连适配器)", "password": False,
             "help": "forward 对应 websocketServers(默认), reverse 对应 websocketClients(反向代理)"},
            {"name": "NAPCAT_TOKEN", "prompt": "访问令牌（可选，留空跳过）", "password": True,
             "help": "与 NapCat Server 配置中 token 字段保持一致，未配置 token 则直接回车跳过"},
            {"name": "NAPCAT_ALLOWED_USERS", "prompt": "允许私聊的 QQ 号（逗号分隔，留空则不限制）", "password": False,
             "is_allowlist": True,
             "help": "白名单：仅允许填写的 QQ 号私聊触发机器人，留空则所有人均可使用"},
            {"name": "NAPCAT_GROUP_ALLOWED_USERS", "prompt": "允许在群聊中触发的 QQ 号（逗号分隔，留空则不限制）", "password": False,
             "help": "群聊白名单：仅允许填写的 QQ 号在群聊中 @ 触发机器人，留空则群内所有人均可触发"},
            {"name": "NAPCAT_ADMIN_USERS", "prompt": "管理员 QQ 号（逗号分隔，留空跳过）", "password": False,
             "help": "拥有 /mute /kick /ban 等管理命令权限的 QQ 号，多个用英文逗号分隔"},
            {"name": "NAPCAT_HOME_CHANNEL", "prompt": "默认投递目标（QQ 号或群号，留空跳过）", "password": False,
             "help": "定时任务结果的默认投递目标：私聊填 QQ 号，群聊填 群号（群聊需加前缀 g:，例如 g:123456789）"},
        ],
    },
'''

if NAPCAT_PLATFORMS_MARKER in content:
    print("  [1/3] _PLATFORMS 条目已存在，跳过")
else:
    # Preferred anchor: before yuanbao entry
    anchor1 = '    {\n        "key": "yuanbao",'
    if anchor1 in content:
        content = content.replace(anchor1, napcat_platform_entry + anchor1, 1)
        print("  [1/3] _PLATFORMS 条目插入成功（yuanbao 之前）")
    else:
        # Fallback: insert before closing bracket + _platform_status
        patched = re.sub(
            r'(\n\]\s*\n\s*\ndef _platform_status)',
            '\n' + napcat_platform_entry + r'\1',
            content, count=1
        )
        if patched != content:
            content = patched
            print("  [1/3] _PLATFORMS 条目插入成功（列表末尾兜底）")
        else:
            print("  [1/3] 警告：未找到 _PLATFORMS 插入点，请手动添加 napcat 条目")

# ════════════════════════════════════════════════════════════════
# Insert 2: _setup_napcat() function
#   Idempotency: check for the exact function signature.
#   Always re-insert when stale (function body may have changed
#   between install.sh versions — e.g. missing NAPCAT_WS_MODE).
# ════════════════════════════════════════════════════════════════
SETUP_FUNC_MARKER = 'def _setup_napcat'
# Marker for content freshness: if WS_MODE prompt is missing the func is stale
SETUP_FUNC_FRESH_MARKER = 'NAPCAT_WS_MODE'

setup_napcat_func = '''

def _setup_napcat():
    """全中文交互式向导：NapCat (QQ via OneBot 11)。"""
    platform = next(p for p in _PLATFORMS if p["key"] == "napcat")
    emoji = platform["emoji"]

    print()
    print(color("  ─── 🐧 NapCat (QQ) 配置向导 ───", Colors.CYAN))

    print()
    for line in platform["setup_instructions"]:
        print_info(f"  {line}")

    existing_http = get_env_value("NAPCAT_HTTP_URL")
    if existing_http:
        print()
        print_success("NapCat 已配置。")
        if not prompt_yes_no("  重新配置 NapCat？", False):
            return

    print()
    print_info("  NapCat HTTP Server 地址，例如 http://127.0.0.1:3000")
    http_url = prompt("  NapCat HTTP API 地址", password=False)
    if not http_url:
        print_warning("  已跳过 — 缺少 HTTP 地址，NapCat 将无法正常工作。")
        return
    save_env_value("NAPCAT_HTTP_URL", http_url.strip().rstrip("/"))
    print_success("  已保存 NAPCAT_HTTP_URL")

    print()
    print_info("  NapCat WebSocket 地址")
    print_info("  正向模式填 WS Server 地址（如 ws://127.0.0.1:3001）")
    print_info("  反向模式填适配器监听地址（如 ws://127.0.0.1:3002）")
    ws_url = prompt("  NapCat WebSocket 地址", password=False)
    if not ws_url:
        print_warning("  已跳过 — 缺少 WebSocket 地址，NapCat 将无法接收消息。")
        return
    save_env_value("NAPCAT_WS_URL", ws_url.strip().rstrip("/"))
    print_success("  已保存 NAPCAT_WS_URL")

    print()
    print_info("  WS 连接模式：forward = 适配器连接 NapCat WS Server（正向，默认）")
    print_info("             reverse = NapCat 连接适配器 WS Server（反向，用于 websocketClients）")
    ws_mode = prompt("  WS 模式 (forward/reverse，默认 forward)", password=False)
    if ws_mode and ws_mode.strip().lower() == "reverse":
        save_env_value("NAPCAT_WS_MODE", "reverse")
        print_success("  已保存 NAPCAT_WS_MODE=reverse（反向代理模式）")
    else:
        print_info("  使用默认正向模式（forward）")

    print()
    print_info("  与 NapCat Server 配置中 token 字段保持一致，未配置 token 则直接回车跳过")
    token = prompt("  访问令牌（可选，留空跳过）", password=True)
    if token:
        save_env_value("NAPCAT_TOKEN", token.strip())
        print_success("  已保存 NAPCAT_TOKEN")
    else:
        print_info("  已跳过（未设置访问令牌）")

    print()
    print_info("  白名单：仅允许填写的 QQ 号私聊触发机器人，留空则所有人均可使用")
    allowed = prompt("  允许私聊的 QQ 号（逗号分隔，留空则不限制）", password=False)
    if allowed:
        save_env_value("NAPCAT_ALLOWED_USERS", allowed.replace(" ", ""))
        print_success("  已保存 NAPCAT_ALLOWED_USERS")
    else:
        print()
        access_choices = [
            "开放访问（所有人均可私聊触发机器人）",
            "暂时跳过（稍后在 .env 中手动配置）",
        ]
        access_idx = prompt_choice("  如何处理未授权用户？", access_choices, 0)
        if access_idx == 0:
            save_env_value("NAPCAT_ALLOW_ALL_USERS", "true")
            print_warning("  已开启开放访问 — 所有人均可使用你的机器人！")
        else:
            print_info("  已跳过")

    print()
    print_info("  群聊白名单：仅允许填写的 QQ 号在群聊中 @ 触发机器人，留空则群内所有人均可触发")
    group_allowed = prompt("  允许群聊触发的 QQ 号（逗号分隔，留空则不限制）", password=False)
    if group_allowed:
        save_env_value("NAPCAT_GROUP_ALLOWED_USERS", group_allowed.replace(" ", ""))
        print_success("  已保存 NAPCAT_GROUP_ALLOWED_USERS")
    else:
        print_info("  已跳过（群聊不限制触发用户）")

    print()
    print_info("  拥有 /mute /kick /ban 等管理命令权限的 QQ 号，多个用英文逗号分隔")
    admins = prompt("  管理员 QQ 号（逗号分隔，留空跳过）", password=False)
    if admins:
        save_env_value("NAPCAT_ADMIN_USERS", admins.replace(" ", ""))
        print_success("  已保存 NAPCAT_ADMIN_USERS")
    else:
        print_info("  已跳过")

    print()
    print_info("  定时任务结果的默认投递目标：私聊填 QQ 号，群聊填 g:<群号>（例如 g:123456789）")
    home = prompt("  默认投递目标（留空跳过）", password=False)
    if home:
        save_env_value("NAPCAT_HOME_CHANNEL", home.strip())
        print_success("  已保存 NAPCAT_HOME_CHANNEL")
    else:
        print_info("  已跳过")

    print()
    print_success(f"{emoji} NapCat (QQ) 配置完成！")
    print_info("  确保 NapCat 已启动并登录 QQ 账号后，运行 hermes gateway 开始使用。")

'''

func_exists = SETUP_FUNC_MARKER in content
func_fresh  = SETUP_FUNC_FRESH_MARKER in content

if func_exists and func_fresh:
    print("  [2/3] _setup_napcat() 已存在且为最新版，跳过")
else:
    if func_exists and not func_fresh:
        # Remove stale version before re-inserting
        # Strip from 'def _setup_napcat' to the next 'def ' at column 0
        content = re.sub(
            r'\ndef _setup_napcat\(\).*?(?=\ndef |\Z)',
            '',
            content,
            count=1,
            flags=re.DOTALL,
        )
        print("  [2/3] 检测到旧版 _setup_napcat()（缺少 NAPCAT_WS_MODE），已移除准备更新")

    # Insert at safe anchor points (avoid breaking if/else blocks)
    # Preferred: after the last top-level function before class Gateway
    inserted = False
    for anchor in [
        'class Gateway:',           # Hermes ≥ 0.11
        'class HermesGateway:',     # older versions
    ]:
        if anchor in content:
            idx = content.find(anchor)
            # Insert right before the class definition
            content = content[:idx] + setup_napcat_func + content[idx:]
            print("  [2/3] _setup_napcat() 函数插入成功（class 之前）")
            inserted = True
            break

    if not inserted:
        # Fallback: append to end of file (safest option)
        content = content.rstrip() + '\n\n' + setup_napcat_func
        print("  [2/3] _setup_napcat() 函数插入成功（文件末尾兜底）")

# ════════════════════════════════════════════════════════════════
# Insert 3: routing branch inside the platform dispatch block
#   Idempotency: check for the napcat dispatch line itself.
#   Anchors tried in order (most to least specific):
#     a) after _setup_qqbot() call  — Hermes ≥ 0.11
#     b) after qqbot key branch     — older layout
#     c) before _setup_standard_platform / _setup_platform call  — 0.10.x
#     d) before wecom branch        — any version with wecom
#     e) append before closing else — last resort
# ════════════════════════════════════════════════════════════════
ROUTE_MARKER = 'platform["key"] == "napcat"'
NAPCAT_ROUTE = '        elif platform["key"] == "napcat":\n            _setup_napcat()\n'

if ROUTE_MARKER in content:
    print("  [3/3] 路由分支已存在，跳过")
else:
    inserted = False

    # Anchor a: after _setup_qqbot()
    for anchor in [
        '            _setup_qqbot()\n',
        'elif platform["key"] == "qqbot":\n            _setup_qqbot()\n',
    ]:
        if anchor in content:
            content = content.replace(anchor, anchor + NAPCAT_ROUTE, 1)
            print("  [3/3] 路由分支插入成功（qqbot 之后）")
            inserted = True
            break

    # Anchor b: before else block that calls _setup_standard_platform / _setup_platform — Hermes 0.10.x
    if not inserted:
        for anchor in [
            '        else:\n            _setup_standard_platform(platform)\n',
            '        else:\n            _setup_platform(platform)\n',
        ]:
            if anchor in content:
                content = content.replace(anchor, NAPCAT_ROUTE + anchor, 1)
                print(f"  [3/3] 路由分支插入成功（else 块之前，0.10.x 兜底）")
                inserted = True
                break

    # Anchor c: before wecom branch
    if not inserted:
        wecom_anchor = '        elif platform["key"] == "wecom":'
        if wecom_anchor in content:
            content = content.replace(wecom_anchor, NAPCAT_ROUTE + wecom_anchor, 1)
            print("  [3/3] 路由分支插入成功（wecom 之前）")
            inserted = True

    # Anchor d: regex — any elif platform["key"] branch
    if not inserted:
        m = re.search(r'(\n        elif platform\["key"\] == "[a-z])', content)
        if m:
            content = content[:m.start()] + '\n' + NAPCAT_ROUTE + content[m.start():]
            print("  [3/3] 路由分支插入成功（正则兜底）")
            inserted = True

    if not inserted:
        print("  [3/3] 警告：找不到路由插入点，请手动在 platform 分发块中添加 napcat 分支")

# Write back only if changed
if content != original:
    open(gateway_py, 'w', encoding='utf-8').write(content)
    import ast
    try:
        ast.parse(content)
        print("  语法验证通过")
    except SyntaxError as e:
        print(f"  语法错误：{e}，正在恢复备份...")
        import shutil
        shutil.copy(gateway_py + '.bak', gateway_py)
        sys.exit(1)
else:
    print("  gateway.py 无需修改")
PYEOF

if [ $? -eq 0 ]; then
    success "gateway.py 修补完成"
else
    error "修补失败，已自动恢复备份"
fi

# ── Step 3: Patch platform registration points ──────────────────
info "Step 3/3  修补平台注册点（platforms.py / send_message_tool.py / config.yaml）"

"$PYTHON_BIN" - "$HERMES_HOME" <<'PYEOF'
import sys, os

hermes_home = sys.argv[1]
any_patched = False

# ── 3a: Patch platforms.py ──
platforms_py = os.path.join(hermes_home, 'hermes_cli', 'platforms.py')
if os.path.isfile(platforms_py):
    content = open(platforms_py, encoding='utf-8').read()
    if '"napcat"' in content:
        print("  [3a] platforms.py 已有 napcat 条目，跳过")
    else:
        old = '("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="hermes-qqbot")),'
        new = '("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="hermes-qqbot")),\n        ("napcat",         PlatformInfo(label="🐱 NapCat (QQ)",     default_toolset="hermes-napcat")),'
        if old in content:
            content = content.replace(old, new, 1)
            open(platforms_py, 'w', encoding='utf-8').write(content)
            print("  [3a] platforms.py napcat 条目插入成功")
            any_patched = True
        else:
            print("  [3a] 警告：platforms.py 中未找到 qqbot 锚点，请手动添加 napcat")
else:
    print("  [3a] 跳过：未找到 platforms.py")

# ── 3b: Patch send_message_tool.py ──
send_msg_py = os.path.join(hermes_home, 'tools', 'send_message_tool.py')
if os.path.isfile(send_msg_py):
    content = open(send_msg_py, encoding='utf-8').read()

    # 3b-1: platform_map entry
    if '"napcat": Platform.NAPCAT' in content:
        print("  [3b-1] send_message_tool.py 已有 napcat 映射，跳过")
    else:
        old = '"qqbot": Platform.QQBOT,'
        new = '"qqbot": Platform.QQBOT,\n        "napcat": Platform.NAPCAT,'
        if old in content:
            content = content.replace(old, new, 1)
            print("  [3b-1] napcat 映射插入成功")
            any_patched = True
        else:
            print("  [3b-1] 警告：未找到 qqbot 锚点，请手动添加 napcat 映射")

    # 3b-2: _send_napcat function
    if 'def _send_napcat(' in content:
        print("  [3b-2] _send_napcat 函数已存在，跳过")
    else:
        napcat_func = r'''
async def _send_napcat(pconfig, chat_id: str, message: str) -> dict:
    """通过 NapCat (QQ) HTTP API 发送消息。"""
    import os
    import httpx

    http_url = os.getenv("NAPCAT_HTTP_URL", "").rstrip("/")
    token = os.getenv("NAPCAT_TOKEN", "")

    if not http_url:
        return _error("NapCat: NAPCAT_HTTP_URL 未配置")

    # 区分私聊和群聊
    if chat_id.startswith("g:") or chat_id.startswith("group:"):
        actual_id = chat_id.split(":", 1)[1]
        msg_type = "group"
    else:
        actual_id = chat_id
        msg_type = "private"

    payload = {
        "user_id" if msg_type == "private" else "group_id": actual_id,
        "message": [{"type": "text", "data": {"text": message}}],
        "message_type": msg_type,
    }

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            resp = await client.post(
                f"{http_url}/send_msg", json=payload, headers=headers
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    msg_id = data.get("data", {}).get("message_id")
                    return {"success": True, "platform": "napcat",
                            "chat_id": chat_id, "message_id": msg_id}
                return _error(f"NapCat API: {data.get('msg', data)}")
            return _error(f"NapCat HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        return _error(f"NapCat send failed: {e}")

'''
        # Try insertion anchors in order
        inserted = False
        for anchor in [
            'async def _send_qqbot',
            'def _send_qqbot',
            'async def _send_wecom',
            'def _send_wecom',
            'async def _send_dingtalk',
            'def _send_dingtalk',
            'async def _send_feishu',
            'def _send_feishu',
        ]:
            if anchor in content:
                content = content.replace(anchor, napcat_func + anchor, 1)
                print(f"  [3b-2] _send_napcat 函数插入成功（锚点：{anchor}）")
                any_patched = inserted = True
                break
        if not inserted:
            content += napcat_func
            print("  [3b-2] _send_napcat 函数追加到文件末尾（无已知锚点）")
            any_patched = True

    # 3b-3: dispatch branch in _send_to_platform
    # NOTE: idempotency check uses the exact dispatch line pattern, NOT
    # "_send_napcat" (the function name), because 3b-2 may insert the
    # _send_napcat function definition after _send_to_platform in the file,
    # which would cause a false-positive skip here.
    napcat_dispatch = '        elif platform == Platform.NAPCAT:\n            result = await _send_napcat(pconfig, chat_id, chunk)\n'
    dispatch_fn_anchor = None
    for candidate in ['def _send_to_platform', 'async def _send_to_platform']:
        if candidate in content:
            dispatch_fn_anchor = candidate
            break
    if dispatch_fn_anchor and 'elif platform == Platform.NAPCAT:' in content.split(dispatch_fn_anchor)[1]:
        print("  [3b-3] _send_to_platform 已有 napcat 分支，跳过")
    elif not dispatch_fn_anchor:
        # Also try: find the dispatch chain using regex (no _send_to_platform function)
        import re
        if re.search(r'elif\s+platform\s*==\s*Platform\.', content):
            dispatch_fn_anchor = '__dispatch_chain__'
        else:
            print("  [3b-3] 警告：未找到 dispatch 函数，跳过 dispatch 插入")
    if dispatch_fn_anchor and (dispatch_fn_anchor == '__dispatch_chain__' or 'elif platform == Platform.NAPCAT:' not in content.split(dispatch_fn_anchor)[1]):
        inserted = False
        # Primary anchor: insert after QQBOT dispatch (most reliable)
        qqbot_patterns = [
            '        elif platform == Platform.QQBOT:\n            result = await _send_qqbot(pconfig, chat_id, chunk)\n',
            '        elif platform == Platform.QQBOT:\n            result = _send_qqbot(pconfig, chat_id, chunk)\n',
            '        elif Platform.QQBOT == platform:\n            result = await _send_qqbot(pconfig, chat_id, chunk)\n',
        ]
        for pattern in qqbot_patterns:
            if pattern in content:
                content = content.replace(pattern, pattern + napcat_dispatch, 1)
                print("  [3b-3] napcat dispatch 插入成功（qqbot 之后）")
                any_patched = inserted = True
                break

        if not inserted:
            # Fallback: insert before "not yet implemented" else clause
            else_anchor = 'else:\n            result = {"error": f"Direct sending not yet implemented for {platform.value}"'
            if else_anchor in content:
                content = content.replace(else_anchor, napcat_dispatch + '        ' + else_anchor, 1)
                print("  [3b-3] napcat dispatch 插入成功（else 之前）")
                any_patched = inserted = True

        if not inserted:
            # Second fallback: regex for any elif platform branch
            import re
            m = re.search(r'(        elif platform == Platform\.[A-Z]+:)', content)
            if m:
                content = content[:m.start()] + napcat_dispatch + content[m.start():]
                print("  [3b-3] napcat dispatch 插入成功（正则兜底）")
                any_patched = inserted = True
            else:
                print("  [3b-3] 警告：未找到 dispatch 插入点，请手动添加 napcat 分支")

        # Strict verification after dispatch insertion attempt
        if 'elif platform == Platform.NAPCAT:' not in content:
            print("  [3b-3] 严重：dispatch 插入验证失败，请手动添加", file=sys.stderr)

    # Write back if changed
    if '"napcat"' not in content or any_patched:
        open(send_msg_py, 'w', encoding='utf-8').write(content)
else:
    print("  [3b] 跳过：未找到 send_message_tool.py")

# ── 3c: Patch config.yaml ──
config_candidates = [
    os.path.join(hermes_home, 'config.yaml'),
    '/opt/data/config.yaml',
    os.path.expanduser('~/.hermes/config.yaml'),
]
config_yaml = None
for c in config_candidates:
    if os.path.isfile(c):
        config_yaml = c
        break

if config_yaml:
    content = open(config_yaml, encoding='utf-8').read()
    if 'napcat:' in content and 'hermes-napcat' in content:
        print(f"  [3c] {config_yaml} 已有 napcat 配置，跳过")
    else:
        old = '  qqbot:\n  - hermes-qqbot'
        new = '  qqbot:\n  - hermes-qqbot\n  napcat:\n  - hermes-napcat'
        if old in content:
            content = content.replace(old, new, 1)
            open(config_yaml, 'w', encoding='utf-8').write(content)
            print(f"  [3c] {config_yaml} napcat 配置插入成功")
            any_patched = True
        else:
            print(f"  [3c] 警告：{config_yaml} 中未找到 qqbot 锚点，请手动添加 napcat")
else:
    print("  [3c] 警告：未找到 config.yaml，请手动添加 napcat 到 platform_toolsets")

# ── 3d: Patch prompt_builder.py (PLATFORM_HINTS) ──
# Without this, the LLM has no QQ-specific context and may treat
# incoming messages as CLI tasks instead of conversational replies.
prompt_builder_py = os.path.join(hermes_home, 'gateway', 'prompt_builder.py')
if os.path.isfile(prompt_builder_py):
    content = open(prompt_builder_py, encoding='utf-8').read()
    if '"napcat"' in content or 'napcat' in content.lower().split('platform_hints')[1][:500] if 'platform_hints' in content.lower() else False:
        print("  [3d] prompt_builder.py 已有 napcat 条目，跳过")
    else:
        napcat_hint = (
            '    "napcat": (\n'
            '        "You are a QQ chat assistant. The user is messaging you via QQ (NapCat/OneBot 11). "\n'
            '        "Reply conversationally. Never call send_message — your reply IS the message sent to QQ."\n'
            '    ),\n'
        )
        # Try inserting after qqbot hint
        for anchor in ['"qqbot":', '"QQBot":']:
            if anchor in content:
                # Find the closing paren+comma of that entry and insert after
                idx = content.find(anchor)
                close = content.find('),', idx)
                if close != -1:
                    content = content[:close+2] + '\n' + napcat_hint + content[close+2:]
                    open(prompt_builder_py, 'w', encoding='utf-8').write(content)
                    print("  [3d] prompt_builder.py PLATFORM_HINTS napcat 条目插入成功")
                    any_patched = True
                    break
        else:
            # Fallback: append before closing brace of PLATFORM_HINTS dict
            import re as _re
            m = _re.search(r'(PLATFORM_HINTS\s*=\s*\{[^}]*)(})', content, _re.DOTALL)
            if m:
                content = content[:m.start(2)] + napcat_hint + content[m.start(2):]
                open(prompt_builder_py, 'w', encoding='utf-8').write(content)
                print("  [3d] prompt_builder.py PLATFORM_HINTS napcat 条目插入成功（兜底）")
                any_patched = True
            else:
                print("  [3d] 跳过：未找到 PLATFORM_HINTS 字典，prompt_builder.py 结构不匹配")
else:
    print("  [3d] 跳过：未找到 prompt_builder.py（可选补丁）")

# ── 3e: Patch gateway/config.py (Platform enum) ──
# The Platform enum lives in config.py, not run.py.
config_py = os.path.join(hermes_home, 'gateway', 'config.py')
if os.path.isfile(config_py):
    content = open(config_py, encoding='utf-8').read()
    if 'NAPCAT = "napcat"' not in content:
        content = content.replace('    QQBOT = "qqbot"', '    QQBOT = "qqbot"\n    NAPCAT = "napcat"')
        open(config_py, 'w', encoding='utf-8').write(content)
        print("  [3e] config.py Platform 枚举添加 NAPCAT")
        any_patched = True
    else:
        print("  [3e] config.py 已有 NAPCAT 枚举，跳过")
else:
    print("  [3e] 跳过：未找到 gateway/config.py")

# ── 3f: Patch gateway/run.py (core GatewayRunner) ──
# Adds NAPCAT support to GatewayRunner (adapter creation, auth maps, update platforms)
run_py = os.path.join(hermes_home, 'gateway', 'run.py')
if os.path.isfile(run_py):
    content = open(run_py, encoding='utf-8').read()
    patched = False


    # 3f-1: Add NAPCAT adapter branch in _create_adapter
    if 'Platform.NAPCAT:' not in content:
        napcat_adapter_code = '''
        elif platform == Platform.NAPCAT:
            from gateway.platforms.napcat import NapCatAdapter, check_napcat_requirements
            if not check_napcat_requirements():
                logger.warning("NapCat: aiohttp/httpx missing or NAPCAT_HTTP_URL/NAPCAT_WS_URL not configured")
                return None
            return NapCatAdapter(config)
'''
        # Try inserting after QQBOT branch
        qqbot_anchor = '        elif platform == Platform.QQBOT:\n            from gateway.platforms.qqbot import QQAdapter, check_qq_requirements\n            if not check_qq_requirements():\n                logger.warning("QQBot: aiohttp/httpx missing or QQ_APP_ID/QQ_CLIENT_SECRET not configured")\n                return None\n            return QQAdapter(config)\n'
        if qqbot_anchor in content:
            content = content.replace(qqbot_anchor, qqbot_anchor + napcat_adapter_code, 1)
            patched = True
            print("  [3f-1] _create_adapter 添加 NAPCAT 分支")

    # 3f-2: Add NAPCAT to _is_user_authorized maps
    if 'Platform.NAPCAT: "NAPCAT_ALLOWED_USERS"' not in content:
        content = content.replace(
            '            Platform.QQBOT: "QQ_ALLOWED_USERS",',
            '            Platform.QQBOT: "QQ_ALLOWED_USERS",\n            Platform.NAPCAT: "NAPCAT_ALLOWED_USERS",'
        )
        content = content.replace(
            '            Platform.QQBOT: "QQ_ALLOW_ALL_USERS",',
            '            Platform.QQBOT: "QQ_ALLOW_ALL_USERS",\n            Platform.NAPCAT: "NAPCAT_ALLOW_ALL_USERS",'
        )
        patched = True
        print("  [3f-2] _is_user_authorized 添加 NAPCAT 权限映射")

    # 3f-3: Add NAPCAT to _UPDATE_ALLOWED_PLATFORMS
    if 'Platform.NAPCAT,' not in content:
        content = content.replace(
            'Platform.BLUEBUBBLES, Platform.QQBOT, Platform.LOCAL,',
            'Platform.BLUEBUBBLES, Platform.QQBOT, Platform.NAPCAT, Platform.LOCAL,'
        )
        patched = True
        print("  [3f-3] _UPDATE_ALLOWED_PLATFORMS 添加 NAPCAT")

    if patched:
        open(run_py, 'w', encoding='utf-8').write(content)
        print("  [3f] run.py 修补完成")
    else:
        print("  [3f] run.py 无需修补")
else:
    print("  [3f] 跳过：未找到 run.py")

# ── 3g: Patch session.py (Platform.NAPCAT branch comment) ──
# Adds a runtime context branch so session logging / toolset selection
# knows this is a QQ conversation, not a CLI or web session.
session_py = os.path.join(hermes_home, 'gateway', 'session.py')
if os.path.isfile(session_py):
    content = open(session_py, encoding='utf-8').read()
    if 'NAPCAT' in content or 'napcat' in content:
        print("  [3g] session.py 已有 napcat 条目，跳过")
    else:
        napcat_branch = '            elif platform == Platform.NAPCAT:\n                ctx["platform_type"] = "qq_chat"\n'
        # Insert after QQBOT branch if present
        for anchor in [
            '            elif platform == Platform.QQBOT:\n',
            'elif platform == Platform.QQBOT:\n',
        ]:
            if anchor in content:
                content = content.replace(anchor, anchor + napcat_branch, 1)
                open(session_py, 'w', encoding='utf-8').write(content)
                print("  [3g] session.py Platform.NAPCAT 分支插入成功")
                any_patched = True
                break
        else:
            print("  [3g] 跳过：未找到 QQBOT 锚点，session.py 结构不匹配（可选补丁）")
else:
    print("  [3g] 跳过：未找到 session.py（可选补丁）")

# === 最终验证 ===
errors = []
for check_file, patterns in [
    (platforms_py, ['"napcat"']),
    (send_msg_py, ['"napcat": Platform.NAPCAT', 'def _send_napcat(', 'elif platform == Platform.NAPCAT:']),
    (config_yaml, ['napcat:', 'hermes-napcat']),
    (config_py, ['NAPCAT = "napcat"']),
    (run_py, ['Platform.NAPCAT:', 'NAPCAT_ALLOWED_USERS']),
]:
    if check_file and os.path.isfile(check_file):
        content = open(check_file, encoding='utf-8').read()
        for pat in patterns:
            if pat not in content:
                errors.append(f"  ✗ {check_file} 缺少 {pat}")

if errors:
    print("\n  验证失败，以下补丁未生效：")
    for e in errors:
        print(e)
    print("  请手动修复以上文件。")
    sys.exit(1)

if any_patched:
    print("")
    print("  ✓ 平台注册点修补完成")
else:
    print("")
    print("  ✓ 平台注册点已就绪（无需修补）")
PYEOF

if [ $? -eq 0 ]; then
    success "平台注册点修补完成"
else
    warn "平台注册点修补出现警告，请检查上方输出"
fi

# ── Done ────────────────────────────────────────────────────────
echo ""
success "安装完成！"
echo ""
echo "  请按顺序执行以下命令："
echo ""
echo "    1. 重启 gateway 使补丁生效："
echo "       hermes gateway restart"
echo ""
echo "    2. 运行配置向导，选择 NapCat (QQ)："
echo "       hermes gateway setup"
echo ""
