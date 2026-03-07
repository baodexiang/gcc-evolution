# QUICKSTART - gcc-evo v5.330

本手册严格按照权威发布口径编写：

- `免费基础层`: `UI + L0 + L1 + L2 + L3`
- `付费核心层`: `L4 + L5 + DA`
- `paid/l0-l3` 属于商业增强包

## 1. 安装

```bash
pip install gcc-evo
gcc-evo version
```

## 2. 免费模式工作流

### 第一步：初始化项目

```bash
gcc-evo init
```

### 第二步：完成 L0 配置

```bash
gcc-evo setup KEY-001
gcc-evo l0 scaffold
gcc-evo l0 check
```

### 第三步：创建任务

```bash
gcc-evo pipe task "Improve retrieval quality" -k KEY-001 -m retrieval -p P1
```

### 第四步：使用免费基础能力

```bash
gcc-evo memory compact
gcc-evo memory export
gcc-evo health
gcc-evo pipe list
gcc-evo pipe status GCC-0001
```

## 3. 付费模式工作流

gcc-evo 最强的工作流从付费核心开始：

```bash
gcc-evo loop GCC-0001 --once
```

这属于付费核心流程，因为它依赖：

- `L4` 决策进化与 Skeptic 验收
- `L5` 闭环编排与漂移感知调度
- `DA` 企业级方向锚定约束

## 4. 定价逻辑

| 层级 | 包含内容 |
|---|---|
| `Community` | `UI + L0 + L1 + L2 + L3` |
| `Evolve` | `Community + paid/l0-l3` |
| `Pro` | `Evolve + L4 + L5` |
| `Enterprise` | `Pro + DA` |

## 5. 稳定性规则

- 免费命令必须在没有付费模块时也能独立运行。
- 付费命令不可静默降级成“看起来可用”，必须明确提示升级边界。
- 对外发布文档必须始终使用 `5 层免费 + 3 层付费` 口径。
