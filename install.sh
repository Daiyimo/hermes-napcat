#!/usr/bin/env bash
# hermes-napcat install script (curl-friendly entry point)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/install.sh | bash
#
# This is a thin wrapper that downloads and runs scripts/install.sh.
# It exists so the URL path stays clean.  The full installer logic is in scripts/install.sh.
set -e

SCRIPT_URL="https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/scripts/install.sh"
PROXY_SCRIPT_URL="https://gh-proxy.com/https://raw.githubusercontent.com/Daiyimo/hermes-napcat/master/scripts/install.sh"

TMPDIR="${TMPDIR:-/tmp}"
INSTALL_SCRIPT="$TMPDIR/hermes-napcat-install-$$.sh"

cleanup() { rm -f "$INSTALL_SCRIPT"; }
trap cleanup EXIT

# Download the real installer
if curl -fsSL --connect-timeout 10 "$SCRIPT_URL" -o "$INSTALL_SCRIPT" 2>/dev/null; then
    :
elif curl -fsSL --connect-timeout 10 "$PROXY_SCRIPT_URL" -o "$INSTALL_SCRIPT" 2>/dev/null; then
    :
elif wget -q --timeout=10 "$SCRIPT_URL" -O "$INSTALL_SCRIPT" 2>/dev/null; then
    :
elif wget -q --timeout=10 "$PROXY_SCRIPT_URL" -O "$INSTALL_SCRIPT" 2>/dev/null; then
    :
else
    echo "错误：无法下载安装脚本，请检查网络连接"
    echo "手动安装: git clone https://github.com/Daiyimo/hermes-napcat.git && cd hermes-napcat && bash scripts/install.sh"
    exit 1
fi

bash "$INSTALL_SCRIPT" "$@"
