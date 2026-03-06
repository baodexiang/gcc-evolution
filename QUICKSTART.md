# QUICKSTART — 10 分钟上手 gcc-evo v5.300

---

## 安装（2 分钟）

```bash
# 克隆或下载源码
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo

# 安装依赖
pip install -e .

# 验证安装
gcc-evo version
# 输出: gcc-evo v5.300
```

---

## 配置（2 分钟）

编辑 `evolution.yaml`（或新建），配置 LLM API：

```yaml
# evolution.yaml
llm_providers:
  gemini:
    api_key: ${GCC_GEMINI_KEY}    # 从环境变量读取
    model: gemini-2.0-pro

  openai:
    api_key: ${GCC_OPENAI_KEY}
    model: gpt-4-turbo

  claude:
    api_key: ${GCC_CLAUDE_KEY}
    model: claude-opus-4

default_provider: claude
```

设置环境变量：
```bash
export GCC_CLAUDE_KEY=sk-ant-...
export GCC_GEMINI_KEY=AIza...
export GCC_OPENAI_KEY=sk-proj-...
```

或复制 `evolution.example.yaml`：
```bash
cp evolution.example.yaml evolution.yaml
# 编辑 evolution.yaml，填入你的 API Key
```

---

## 初始化项目（1 分钟）

```bash
# 创建 .GCC/ 目录和必要文件
gcc-evo init

# 文件结构
.GCC/
├── gcc.db              # 改善历史数据库
├── pipeline/
│   └── tasks.json      # 任务管道
├── state/
│   └── improvements.json  # KEY/改善项定义
└── handoff/            # 交接文档
```

---

## L0 预先设置（新！必须先做）

v5.300 新增：每次 loop 前必须先完成 L0 配置。

```bash
# 首次配置（交互式向导）
gcc-evo setup KEY-010

# 向导会依次询问：
#   KEY编号:       KEY-010
#   进化目标:      提升信号准确率（至少10字）
#   成功标准:      1. 信号准确率>80%
#                  2. 误报率<10%
#   人工确认:      Y/n（每轮结束是否暂停等待确认）
#   最大循环次数:  0=不限
#   备注:          （可选）

# 查看当前配置
gcc-evo setup --show

# 编辑某个字段
gcc-evo setup --edit

# 重置配置（重新填写）
gcc-evo setup --reset
```

配置存储在 `.GCC/state/session_config.json`。

---

## 核心工作流（5 分钟）

### 1. 定义改善方向（KEY）

```bash
# 先完成 L0 KEY 配置
gcc-evo setup KEY-001
```

输出示例：
```
KEY-001: 提高交易信号准确率
KEY-002: 降低虚假信号
...
```

### 2. 创建任务

```bash
# 为 KEY-001 创建任务
gcc-evo pipe task "改善信号准确率 Phase 1" -k KEY-001 -m core -p P1
```

### 3. 运行 Loop 闭环

```bash
# 前提：先完成 L0 配置（gcc-evo setup KEY-010）

# 单次闭环（分析→蒸馏→更新）
gcc-evo loop GCC-0001 --once

# 持续闭环（每 5 分钟自动运行）
gcc-evo loop GCC-0001

# 测试用：跳过 L0 gate
gcc-evo loop GCC-0001 --once --dry-run
```

Loop 会自动执行：
1. **Tasks** — 读取任务进度
2. **Audit** — 分析日志，发现问题
3. **Cards** — 生成经验卡
4. **Rules** — 提取可复用规则
5. **Distill** — 蒸馏到 SkillBank
6. **Report** — 显示闭环摘要

示例输出：
```
🔄 Loop Cycle: GCC-0001
═══════════════════════════════════════
✓ Step 1: Tasks [2/5 done]
✓ Step 2: Audit [5 issues found]
  - Issue-1: 信号延迟 100ms
  - Issue-2: 虚假突破触发率 12%
✓ Step 3: Cards [新增 3 张经验卡]
✓ Step 4: Rules [提取 5 条规则]
✓ Step 5: Distill [SkillBank +2 技能]
✓ Step 6: Report [预计改善: +3% 准确率]

Status: HEALTHY
Next Iteration: 5 minutes
```

### 4. 查看进度

```bash
# 健康检查
gcc-evo health

# 查看当前 L0 配置
gcc-evo setup --show

# 查看任务详情
gcc-evo pipe status GCC-0001
```

---

## 常用命令速查

| 命令 | 说明 |
|------|------|
| `gcc-evo setup KEY-010` | L0 配置向导（必须先做） |
| `gcc-evo setup --show` | 查看当前 L0 配置 |
| `gcc-evo setup --edit` | 编辑 L0 配置字段 |
| `gcc-evo init` | 初始化项目结构 |
| `gcc-evo loop GCC-001 --once` | 单次闭环 |
| `gcc-evo loop GCC-001 --dry-run` | 跳过 L0 gate 测试 |
| `gcc-evo pipe task "标题" -k KEY-001 -m core -p P1` | 创建任务 |
| `gcc-evo pipe list` | 列出所有任务 |
| `gcc-evo memory compact` | 压实长期记忆 |
| `gcc-evo health` | 系统健康检查 |

---

## 切换 LLM 模型

gcc-evo 支持无缝切换模型，无损上下文：

```bash
# 用 Gemini 跑本次 loop
gcc-evo loop GCC-0001 --provider gemini --once

# 用 OpenAI 跑一次 loop
gcc-evo loop GCC-0001 --provider openai --once

# 多模型协作（Skeptic 验证）
# 默认用 claude 决策，gemini + openai 验证
gcc-evo loop GCC-0001 --once
```

---

## 故障排查

### 问题 1：API Key 找不到

```
Error: GCC_CLAUDE_KEY not set
```

**解决**：
```bash
export GCC_CLAUDE_KEY=你的key
# 或编辑 evolution.yaml，直接填入 key
```

### 问题 2：权限不足

```
PermissionError: [Errno 13] Permission denied: '.GCC/gcc.db'
```

**解决**：
```bash
chmod +x .GCC
chmod 644 .GCC/gcc.db
```

### 问题 3：Loop 卡住

```bash
# 查看日志
tail -f .GCC/logs/loop.log

# 强制中止
Ctrl+C

# 重新初始化项目结构
gcc-evo init
```

---

## 下一步

- 👉 完整文档：[README.md](README.md)
- 🔒 安全政策：[SECURITY.md](SECURITY.md)
- 🤝 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 📚 高级用法：`gcc-evo help <command>`

---

**祝你用得愉快！**

有问题？[提交 Issue](https://github.com/baodexiang/gcc-evo/issues)
