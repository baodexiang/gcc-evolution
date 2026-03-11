# gcc-evo v5.345

另见: [FRAMEWORK_BOUNDARY.md](FRAMEWORK_BOUNDARY.md) | [FRAMEWORK_BOUNDARY.en.md](FRAMEWORK_BOUNDARY.en.md) | [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md) | [PRICING.md](PRICING.md)

`gcc-evo` 当前对外只有一套权威口径：

- `5 层免费基础层`: `UI`、`L0`、`L1`、`L2`、`L3`
- `3 层付费核心层`: `L4`、`L5`、`DA`
- `paid/l0-l3` 是商业增强包，不额外计入顶层层数

## 免费基础层

| 层 | 职责 | 常用命令 |
|---|---|---|
| `UI` | 看板、状态可视化、基础运维入口 | `gcc-evo version`、`gcc-evo health` |
| `L0` | 初始化、前提校验、会话启动 | `gcc-evo setup KEY-001`、`gcc-evo l0 scaffold`、`gcc-evo l0 check` |
| `L1` | 持久化记忆 | `gcc-evo memory compact`、`gcc-evo memory export` |
| `L2` | 检索与标准化 | 免费基础模块内置能力，opensource 当前不提供独立 CLI 命令 |
| `L3` | 蒸馏与技能沉淀 | 免费基础模块内置能力，主要通过 `pipe` 和运行产物体现 |

## 付费核心层

| 层 | 职责 | 设计目的 |
|---|---|---|
| `L4` | 决策进化、Skeptic 验收、基准接受判定 | 把原始结果变成可验收的受控决策 |
| `L5` | 闭环编排、自适应调度、漂移感知执行 | 把分散工具变成真正自进化运行闭环 |
| `DA` | Direction Anchor 宪法级约束 | 保证系统不偏离核心战略和红线 |

## 商业增强包

`paid/l0`、`paid/l1`、`paid/l2`、`paid/l3` 用于增强免费基础层的治理、记忆质量、检索质量和蒸馏质量。它们属于商业模块，但不改变对外层级口径。

对外必须始终表述为：

- `5 层免费 + 3 层付费`

## gcc-evo 最强功能的设计目的

gcc-evo 最强的部分不是单独的记忆或检索，而是付费核心层形成的受控进化引擎：

1. `L4` 负责可量化的决策验收
2. `L5` 负责闭环运行与漂移感知调度
3. `DA` 负责宪法级方向控制

没有这三层，gcc-evo 是一个很强的基础框架；有了这三层，gcc-evo 才真正成为可治理的自进化引擎。

## 安装

```bash
pip install gcc-evo
gcc-evo version
```

## 免费模式工作流

```bash
gcc-evo init
gcc-evo setup KEY-001
gcc-evo l0 scaffold
gcc-evo l0 check
gcc-evo l0 set-prereq data_quality --status pass --evidence "acceptance"
gcc-evo l0 set-prereq deterministic_rules --status pass --evidence "acceptance"
gcc-evo l0 set-prereq mathematical_filters --status pass --evidence "acceptance"
gcc-evo pipe task "Improve retrieval quality" -k KEY-001 -m retrieval -p P1
gcc-evo pipe list
gcc-evo pipe status GCC-0001
gcc-evo memory compact
gcc-evo memory export
gcc-evo health
gcc-evo loop DEMO-001 --once --dry-run
```

## OCR 与知识卡流程

OCR 和卡片生成目前以仓库脚本形式提供，不是 `gcc-evo` 子命令。

```bash
python ocr_pdf.py paper.pdf output_cards
python pdf_to_cards_v3.py output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine
```

如果已经配置 LLM，可以继续精修：

```bash
python pdf_to_cards_v3.py output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine --llm-refine --llm-repeat 3
```

这条流程会产出：

- `page_*.md` 页文本
- `page_*.json` 结构化知识卡
- 可选 DuckDB 卡片入库

## 付费模式工作流

```bash
gcc-evo loop GCC-0001 --once
```

在权威 `v5.345` 口径里，`loop` 属于付费核心流程，因为它依赖 `L4 + L5` 的决策进化与闭环编排。
开源包同时保留了 `gcc-evo loop DEMO-001 --once --dry-run` 这条社区版 smoke path。
如果要跑非 `--dry-run` 的 loop，先把上面的 3 个 `L0 prerequisite` 都设为 `pass`。

## 定价

| 层级 | 包含内容 |
|---|---|
| `Community` | `UI + L0 + L1 + L2 + L3` |
| `Evolve` | `Community + paid/l0-l3` |
| `Pro` | `Evolve + L4 + L5` |
| `Enterprise` | `Pro + DA + 企业部署` |

## 发布规则

- 免费层必须能独立运行。
- 付费层必须显式提示升级边界，不能假装可用。
- legacy 模块可以保留兼容，但不能定义商业边界。
- README、Quickstart、手册、压缩包必须统一使用 `5 层免费 + 3 层付费` 口径。
