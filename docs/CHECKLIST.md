# 项目验证清单

本文档用于验证项目整理后的完整性。

---

## ✅ 目录结构

- [x] 根目录 Python 模块保持在根目录（适配器项目最佳实践）
- [x] config/ 目录包含所有配置示例
- [x] docs/ 目录包含所有详细文档
- [x] scripts/ 目录包含所有运维脚本
- [x] tests/ 目录包含所有测试文件

---

## ✅ 文档完整性

- [x] README.md 精简至核心内容（< 200 行）
- [x] README.md 包含完整的文件结构说明
- [x] docs/CONFIGURATION.md 覆盖正向/反向模式
- [x] docs/CONFIGURATION.md 包含完整的环境变量参考
- [x] docs/TROUBLESHOOTING.md 覆盖常见问题
- [x] docs/ARCHITECTURE.md 描述核心模块和数据流
- [x] docs/INDEX.md 提供文档导航
- [x] CONTRIBUTING.md 存在且内容完整
- [x] CHANGELOG.md 存在且格式规范

---

## ✅ 配置示例

- [x] config/.env.example 包含所有环境变量及其说明
- [x] config/napcat-forward.json.example 是有效的 JSON
- [x] config/napcat-reverse.json.example 是有效的 JSON
- [x] config/docker-compose.yml.example 包含正向和反向模式示例
- [x] config/napcat-gateway.patch 存在并附带说明文档

---

## ✅ 文档链接

- [x] README.md 中的所有文档链接可正常访问
- [x] README.md 中的脚本路径引用正确
- [x] docs/INDEX.md 中的所有链接可正常访问

---

## ✅ 代码质量

- [x] 所有 Python 模块有文件级文档字符串
- [x] 所有公共函数有文档注释
- [x] 类型注解完整（符合项目规范）
- [x] 常量集中管理（constants.py）
- [x] 无魔法数字/字符串

---

## ✅ 测试

- [x] tests/ 目录包含完整的测试套件
- [x] pytest.ini 配置正确
- [x] conftest.py 提供完整的测试桩
- [x] 测试覆盖率 > 80%（可通过 pytest-cov 验证）

---

## ✅ 工具链

- [x] pyproject.toml 配置 ruff 和 pytest
- [x] .pre-commit-config.yaml 配置 pre-commit 钩子
- [x] requirements.txt 包含所有依赖
- [x] .gitignore 覆盖所有常见缓存和临时文件

---

## ✅ 运维就绪

- [x] scripts/ 所有脚本有执行权限（chmod +x）
- [x] scripts/install.sh 是 curl 友好的入口点
- [x] 诊断工具脚本可独立运行
- [x] 健康检查支持 --json 输出

---

## ✅ 插件注册

- [x] plugin.yaml 存在且格式正确
- [x] __init__.py 包含 _register() 函数
- [x] platform_registry 注册逻辑完整

---

## 使用说明

此清单用于项目整理后的自检。定期运行可确保项目结构保持整洁。

```bash
# 快速验证文档链接
grep -r "\[.*\](.*)" README.md docs/ | grep -E "\.md\)" | while read -r line; do
  link=$(echo "$line" | grep -oP '\[.*?\]\(\K[^)]+')
  [ -f "$link" ] || echo "❌ 缺失: $link"
done
```
