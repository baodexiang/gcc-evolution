# CHANGELOG — gcc-evo 版本历史

所有变更记录在本文件中。本项目遵循 [Semantic Versioning](https://semver.org/) 规范。

---

## [5.305] — 2026-03-06

### 🔧 变更 (Changed)

- 发布版本升级到 **5.305**（`setup.py`、`gcc_evolution/__init__.py`、初始化模板版本字段）。
- 开源模块头部版本标记从 `v5.300`/`v5.301` 统一更新为 `v5.305`。
- 用户手册交付更新到 `v5_305`：
  - `GCC_Beginners_Guide_v5_305.docx`
  - `GCC_新手完全手册_v5_305.docx`
- 重新生成源码压缩包 `gcc_evolution_v5305.zip`。

---

## [5.301] — 2026-03-06

### 🔧 修复 (Fixed)

- **新增 `gcc-evo commit` 命令**：提交代码时可关联 `GCC-xxxx` 与 `Sx`，并在 commit 成功后自动同步 `.GCC/pipeline/tasks.json`，确保 Dashboard 任务状态实时更新。
- **自动交接触发**：当 commit 识别到任务号/步骤号时，自动尝试执行 `gcc-evo ho create`（失败给出 warning，不影响 commit 成功）。
- **版本更新**：包版本从 `5.300` 升级到 `5.301`（`__init__.py`、`setup.py`、Dashboard 版本展示、初始化模板版本号同步）。

---

## [5.300] — 2026-03-05

### ✨ 新增 (New)

- **L0 预先设置层** — `gcc-evo setup` 交互式向导，每次 loop 前强制通过 L0 gate
  - `SessionConfig` — 存储 `.GCC/state/session_config.json`，3个必填字段验证
  - `gcc-evo setup KEY-010` — 交互式填写目标/成功标准/配置
  - `gcc-evo setup --show` — 查看当前配置
  - `gcc-evo setup --edit` — 编辑单个字段
  - `gcc-evo setup --reset` — 重置配置
- **L6 观测层** — 完整实时观测框架
  - `EventBus` — 线程安全单例事件总线，<5ms emit，持久化到 `.GCC/logs/events.jsonl`
  - `LayerEmitter` — 七层语义化 emit 接口 (`emit_l0~l6`, `layer_start/done/error`)
  - `RunTracer` — 按 loop_id 追踪每次运行的全流程快照
  - `DashboardServer` — 本地 HTTP 服务 (端口 7842)，SSE 实时推送，15秒心跳
- **实时 Dashboard** — 七层状态可视化，暗色主题，SSE 自动重连，运行历史面板
- **`gcc-evo loop --dry-run`** — 跳过 L0 gate 检查（用于测试）

### 🎯 改进 (Improved)

- `gcc-evo version` — 现在显示 L6:Observation 层状态
- `gcc-evo loop` — 增加 L0 gate：配置无效时拒绝启动并提示 `gcc-evo setup`
- `cli.py` — 新增 `setup` 子命令路由

### 🔧 技术细节

- **EventBus `_writer_loop`** — 跨批次 `unflushed` 列表累积，达到阈值才写盘，线程退出时最终 flush
- **ThreadingHTTPServer** — `daemon_threads=True`，SSE 线程不阻塞 `stop()`；`stop()` 调用 `shutdown()` + `server_close()` 确保端口可复用
- **RunTracer `_on_event`** — 自动推断层状态 (started/done/error/skipped)，无需手动调用 `mark_layer`

---

## [5.295] — 2026-03-03

### ✨ 新增 (New)

- **Loop 闭环命令** — 一键运行完整改善闭环 (6步自动执行)
  - `gcc-evo loop GCC-0001 --once` — 单次闭环
  - `gcc-evo loop GCC-0001` — 持续闭环 (5分钟自动重复)
- **跨模型切换** — 支持 Gemini/ChatGPT/Claude/DeepSeek 无缝切换
- **外挂信号准确率闭环** — 自动追踪和改善外挂信号质量
  - 信号记录 + 4H 回填验证 + Phase 升降级 + 品质日报
- **Skeptic 验证门控** — 阻止未验证结论写入内存
- **可视化看板** — 单文件 HTML，无需安装

### 🐛 修复 (Fixed)

- 环境变量泄露 — 错误消息中敏感变量现显示为 `[MASKED]`
- N 字门控品质阈值 — 从 0.65 → 0.55，放行正常回调边际信号
- x4 大周期方向限制 — 禁用过度限制条件，准确率提升
- 历史修复条目显示 — fixed 规则无匹配时也作为已修复显示

### 🎯 改进 (Improved)

- 内存管理 — 三级分层 (sensory/short/long) 优化长期记忆
- 检索精度 — RAG + 语义检索 + KNN 历史相似度
- 经验蒸馏 — 自动提炼可复用规则到 SkillBank
- 审计日志 — 结构化 JSON 日志记录所有 LLM 交互

### 📚 文档 (Documentation)

- README.md — 完整的项目背景和架构说明
- QUICKSTART.md — 10 分钟上手指南
- CONTRIBUTING.md — 贡献工作流和 CLA 流程
- SECURITY.md — 安全政策和最佳实践
- LICENSE — BUSL 1.1 + Additional Use Grant
- CONTRIBUTOR_LICENSE_AGREEMENT.md — 个人 CLA
- ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.md — 企业 CLA

### 🔧 技术细节

- **Memory Tiers** — Sensory (最新事件) / Short-term (最近讨论) / Long-term (总结知识)
- **Retriever** — 语义相似度 + KNN 时间加权 + BM25 关键词
- **Distiller** — 经验卡 → SkillBank，支持自动版本化
- **Skeptic** — Confidence 阈值 (默认 0.75) + Human Anchor 验证
- **Pipeline** — DAG 任务调度 + 依赖管理 + 重试逻辑

---

## [5.290] — 2026-03-01

### ✨ 新增 (New)

- **gcc-evo v5.290** — AI 自进化引擎首个完整版本发布
- **Loop 命令绑定** — 将任务与改善闭环关联
- **开源发布包** — 完整的 P0 文档和工具集合
  - Paper Engine — 论文分析和知识蒸馏
  - Vision Analyzer — 图像识别和形态分析
  - Plugin Registry — 外挂系统和评分机制

### 🎯 改进 (Improved)

- 仓库结构重组 — 分离 `.GCC/`、`opensource/`、`modules/`
- 版本号标准化 — 采用 `v X.YZZ` 格式 (v5.290, v5.295)
- 日志输出规范化 — 统一 `[v5.xxx]` 和 `[symbol]` 前缀

### 📦 发行物 (Releases)

- gcc_evolution_v5290.zip — 开源文档和许可证包
- GCC_新手完全手册_v5_290.docx — 中文使用说明书
- GCC_Beginners_Guide_v5_290.docx — 英文使用说明书

---

## [4.98] — 2025-12-15

### ✨ 新增 (New)

- **初始 gcc-evo** — GCC Evolution Engine 原型版本
- **基础记忆系统** — 会话内 Token 管理
- **简单检索** — 基于关键词的内容查找
- **经验卡系统** — 手动创建和管理

### 📝 架构设计

- 单层记忆 (会话级)
- 关键词匹配
- 静态技能库
- 手工操作驱动

---

## [3.0] — 2025-10-01

### ✨ 新增 (New)

- **第一代 GCC** — Bug 追踪和改善记录系统
  - Issue 管理
  - Fix 记录
  - 验证流程

### 📝 原型

- 文本文件存储
- 手动整理
- 基础统计

---

## 版本演进路线图

```
v3.0 (Bug Tracker)
    ↓
v4.0 (Improvement Manager)
    ↓
v4.98 (GCC Prototype)
    ↓
v5.0 (Memory Tiers Introduction)
    ↓
v5.100 (Retrieval Layer)
    ↓
v5.200 (Distillation Engine)
    ↓
v5.290 (Open Source Release)
    ↓
v5.295 (Current) — Loop + Skeptic + Multi-Model
    ↓
v6.0 (Planned) — Distributed Memory + Real-time Collaboration
```

---

## 升级指南

### 从 v5.290 升级到 v5.295

**无破坏性更新**，所有 API 保持向后兼容。

```bash
# 更新包
pip install --upgrade gcc-evo

# 检查版本
gcc-evo version
# 输出: gcc-evo v5.295

# 运行迁移 (可选，自动处理)
gcc-evo migrate
```

**新功能使用**：
```bash
# 开启 Loop 闭环
gcc-evo loop GCC-0001 --once

# 指定 LLM 模型
gcc-evo loop GCC-0001 --provider gemini --once

# 持续运行 (生产环境)
gcc-evo loop GCC-0001 &
```

---

## 已知问题和限制

### v5.295

- **Token 窗口** — 单次对话仍受 LLM 上下文限制 (claude-opus: 200K tokens)
  - 缓解: 自动内存压缩和检索策略
- **LLM 幻觉** — 模型可能生成虚假内容
  - 缓解: Skeptic 验证门控 (confidence < 0.75 阻止)
- **冷启动** — 新项目首次运行需要初始化
  - 缓解: `gcc-evo init` 自动设置

### 性能

- **首次检索** — ~2-3 秒 (KNN 索引构建)
- **Distillation** — ~5-10 秒 (LLM 调用)
- **Loop 周期** — 5-15 分钟 (取决于任务复杂度)

---

## 贡献者致谢

本项目由 baodexiang 开发，感谢以下贡献者：

- 论文研究和选型 — arXiv 论文分析 (30+ 篇评分 4.0+)
- 外挂系统设计 — Plugin Registry 和 KNN 匹配
- 用户反馈和测试 — 来自交易系统和工业诊断场景

---

## 许可证

- **v5.295 及之前** — BUSL 1.1 (2028-05-01 自动转为 Apache-2.0)
- **v6.0 及以后** — Apache 2.0 (从计划开始)

详见 [LICENSE](LICENSE) 文件。

---

## 反馈和报告

- 🐛 **Bug 报告** — GitHub Issues 或 baodexiang@hotmail.com
- 💬 **功能建议** — GitHub Discussions
- 🔐 **安全问题** — security@gcc-evo.dev (私密)

---

**最后更新**: 2026-03-03
**版本**: 5.295
**维护者**: baodexiang <baodexiang@hotmail.com>
