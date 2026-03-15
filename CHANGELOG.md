# CHANGELOG - gcc-evo 版本历史

所有公开版本变更记录都保存在本文件中。项目遵循 [Semantic Versioning](https://semver.org/)。

---

## [5.420] - 2026-03-15

### Added

- GCC-0270: 知识卡闭环进化系统 — 卡片从提取到淘汰的完整生命周期
  - `card_bridge.py` 纳入 opensource (原仅在私有仓)
  - KNN经验记录新增 `card_ids` 字段，关联交易决策与知识卡
  - `_backfill_outcome()` 回填交易结果时同步调用 `card_bridge.record_outcome()` 给卡片打分
  - 每日8AM蒸馏后追加 `prune_deprecated()` 淘汰正确率<30%的卡 + `distill_to_skills()` 高分卡蒸馏为skill
  - B1通道每30分钟读取 top3(skill/causal) + 随机2张(探索) = 5张卡片参与决策
- 新增7本交易书籍知识卡 (183张，总计1170张): Chart Patterns ML, Wyckoff Methodology, Wyckoff 2.0 Structures, Ultimate Price Action, Successful Breakout, Wyckoff Integration, 量价时空完整版

### Changed

- 版本号统一升级到 `5.420`
- 知识卡按书名归类到子目录: `skill/cards/{书名}/CARD-*.json`
- `INDEX.md` 更新卡片总数 987→1170，新增书籍索引和主题查找表

## [5.410] - 2026-03-14

### Added

- GCC-0250 S09: TiM merge-near-samples — `_knn_smart_prune_v2()` 新增 Phase2 cosine 聚类合并相似特征向量
- GCC-0250 S03: StockMem 因果三元组检索激活 — retriever._score() causal_boost
- GCC-0262: Brooks Vision 增强 — 标注图 v2.0 + Prompt V2 + 解析适配

### Changed

- 版本号统一升级到 `5.410`
- 重新生成源码压缩包 `gcc_evolution_v5410.zip`
- 删除旧压缩包 v5401/v5405

## [5.405] - 2026-03-12

### Changed

- opensource 当前源码与当前目录主程序统一升级到 `5.405`
- 纳入最新 KEY-007 改善: 自适应 KNN、WFO Phase Gate、per-plugin×symbol 准确率矩阵/热力图日报
- 重新生成源码压缩包 `gcc_evolution_v5405.zip`

## [5.400] - 2026-03-11

### Changed

- opensource 当前源码版本升级到 `5.400`
- 用户手册入口更新到 `v5.400`
- 重新生成源码压缩包 `gcc_evolution_v5400.zip`
