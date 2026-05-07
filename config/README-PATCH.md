# NapCat Gateway 补丁文件

## 用途

此补丁用于在 Hermes Agent 安装完成后，自动为 `gateway.py` 添加 NapCat 平台的交互式配置向导。

## 何时使用

仅在**手动安装**且未使用 `scripts/install.sh` 自动安装时需要。

安装脚本 `scripts/install.sh` 会自动完成此补丁的应用，**无需手动操作**。

## 手动应用方法

如果确实需要手动应用补丁：

```bash
cd /path/to/hermes
patch -p1 < /path/to/hermes-napcat/config/napcat-gateway.patch
```

## 补丁内容

- 在 `_PLATFORMS` 列表中添加 NapCat 平台配置项
- 新增 `_setup_napcat()` 函数（全中文交互式向导）
- 在平台设置流程中注册 NapCat 配置入口

## 注意事项

- 补丁基于 Hermes Agent v0.11.0 开发，版本不匹配可能导致冲突
- 应用补丁后需重启 Hermes Gateway：`hermes gateway restart`
- 如 Hermes 升级后出现冲突，可重新运行 `scripts/install.sh` 重新应用
