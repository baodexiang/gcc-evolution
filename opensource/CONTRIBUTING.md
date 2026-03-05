# 贡献指南 / Contributing

感谢你对 gcc-evo 的兴趣！我们欢迎各种形式的贡献。

---

## 贡献流程

### 1. 提交 Issue（讨论改进方向）

在提交 PR 前，请先开 Issue 讨论：

```bash
# Issue 类型
- Bug report: 发现的问题
- Feature request: 新功能建议
- Enhancement: 现有功能改进
- Documentation: 文档改进
```

**Issue 模板：**

```markdown
## 问题描述
简明清晰地描述问题或建议

## 为什么需要这个改进？
为什么这个改进很重要

## 建议方案（可选）
你的解决思路

## 上下文信息
- gcc-evo 版本：v5.290
- Python 版本：3.9+
- 操作系统：Linux / macOS / Windows
```

### 2. Fork 和本地开发

```bash
# Fork 项目
git clone https://github.com/YOUR_USERNAME/gcc-evo.git
cd gcc-evo

# 创建功能分支
git checkout -b feature/your-feature-name

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试确保基线通过
pytest tests/
```

### 3. 代码规范

遵循 PEP 8 + 项目风格：

```python
# ✅ 好的例子
def analyze_memory_tier(tier_name: str) -> Dict[str, Any]:
    """
    分析内存层的状态。

    Args:
        tier_name: 内存层名称 ('sensory', 'short', 'long')

    Returns:
        内存层统计信息字典

    Raises:
        ValueError: 如果 tier_name 不有效
    """
    if tier_name not in ['sensory', 'short', 'long']:
        raise ValueError(f"Invalid tier: {tier_name}")

    return self._tiers[tier_name].stats()

# ❌ 避免
def analyze(tn):
    # 分析内存
    return tiers[tn].stat
```

**关键规范：**
- 类型注解（PEP 484）必须
- Docstring 使用 Google 风格
- 最大行长 100 字符
- 函数/方法最多 50 行（复杂逻辑分离）
- 避免单字母变量（i, x, y 除外）

### 4. 提交 PR

```bash
# 提交前：
1. 运行测试：pytest tests/
2. 运行格式检查：black . && isort .
3. 运行类型检查：mypy gcc_evolution/

# 提交 PR
git push origin feature/your-feature-name
```

**PR 模板：**

```markdown
## 改进说明
简明描述这个 PR 做了什么

## 相关 Issue
Fixes #123

## 测试方案
- [ ] 新增单元测试
- [ ] 运行 `pytest tests/` 全部通过
- [ ] 手动测试步骤：
  1. ...
  2. ...

## 检查清单
- [ ] 代码遵循项目风格
- [ ] 添加了必要的文档
- [ ] 更新了 CHANGELOG.md
- [ ] 无新的 linting warnings
```

---

## Contributor License Agreement (CLA)

首次贡献时，你需要同意 CLA：

### 个人贡献者 CLA

```
I agree to license my contributions under the BUSL 1.1 license
and future Apache 2.0 as per the conversion date (2028-05-01).

I represent that I am the copyright owner of my contributions
or have been authorized to make contributions on behalf of the copyright owner.
```

### 企业贡献者 CLA

企业用户需要：
1. 由授权代表（如法务）签署企业 CLA
2. 清明列出贡献者名单
3. 确认使用的许可证版本

**流程：**
1. 提交第一个 PR
2. 机器人评论要求签署 CLA
3. 点击链接在线签署或下载签署
4. PR 自动解除 CLA 阻塞

CLA 文本位置：
- 个人：[CONTRIBUTOR_LICENSE_AGREEMENT.md](./CONTRIBUTOR_LICENSE_AGREEMENT.md)
- 企业：[ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.md](./ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.md)

---

## 代码审查标准

### 什么会被接受

✅ **核心架构改进**
- 更好的内存管理
- 更快的检索算法
- 更强的验证门控

✅ **Bug 修复**
- 清晰的根因分析
- 测试验证
- 风险评估

✅ **文档改进**
- 代码注释补全
- API 文档更新
- 示例代码

### 什么可能被拒绝

❌ **破坏性变更**
- 改变公共 API 签名（无版本计划）
- 删除已发布的功能

❌ **未经测试的代码**
- 无单元测试
- 无手动测试方案

❌ **超出范围的改进**
- 非核心功能的大型重构
- 第三方集成（应通过插件系统）

---

## 开发环境设置

### 依赖安装

```bash
# 基础依赖
pip install -e .

# 开发工具
pip install -e ".[dev]"
# 包括: pytest, black, isort, mypy, flake8

# 可选：本地 LLM
pip install -e ".[local-llm]"
```

### 运行测试

```bash
# 全部测试
pytest tests/ -v

# 特定模块
pytest tests/test_memory_tiers.py -v

# 覆盖率
pytest tests/ --cov=gcc_evolution --cov-report=html
```

### 本地开发工作流

```bash
# 1. 开发分支
git checkout -b feature/xxx

# 2. 编写代码 + 测试
# 编辑 gcc_evolution/xxx.py
# 编辑 tests/test_xxx.py

# 3. 运行检查
pytest tests/test_xxx.py   # 测试
black gcc_evolution/       # 格式化
mypy gcc_evolution/        # 类型检查

# 4. 提交
git add .
git commit -m "feat: add xxx feature"
git push origin feature/xxx

# 5. 创建 PR
# 访问 GitHub，填写 PR 模板
```

---

## 提交信息规范

使用 Conventional Commits：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type:**
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档
- `style`: 代码风格（无逻辑改变）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建、依赖等

**示例：**
```
feat(memory_tiers): add LRU eviction policy

Implement Least Recently Used eviction for sensory tier
to prevent unbounded growth in long-running sessions.

- Add EvictionPolicy interface
- Implement LRUEvictionPolicy
- Add tests for eviction behavior

Fixes #456
```

---

## 报告安全问题

**不要**在 GitHub Issue 或 PR 中报告安全漏洞。

见 [SECURITY.md](./SECURITY.md) 的私密报告流程。

---

## 获得帮助

- 💬 **讨论**：开 Discussion 提问
- 🐛 **Bug**：提交 Issue
- 💡 **想法**：开 Issue 讨论
- 📧 **直接联系**：baodexiang@hotmail.com

---

## 致谢

感谢所有对 gcc-evo 做出贡献的人。每个 PR、Issue、文档改进都帮助我们构建更好的工具。

贡献者名单维护在 [CONTRIBUTORS.md](./CONTRIBUTORS.md)

---

**开心编码！** 🚀
