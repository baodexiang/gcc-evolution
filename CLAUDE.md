# 项目指令

## 启动时自动读取

每次任务前先读取：
1. .GCC/ENTRYPOINTS.md
2. .GCC/skill/evolution-log.md
3. .GCC/branches/master/handoff.md（最新 handoff，了解上一次变更）

## 结构真相源

程序结构与正式运行入口统一以 `.GCC/ENTRYPOINTS.md` 为准。

- `.GCC/skill/SKILL.md` 仅作为 GCC/skill 体系说明
- `.GCC/skill/INDEX.md` 仅作为知识索引
- `.claude/skills/codemap-llm-server-v3570/` 仅作为历史镜像

## 代码修改后（自动执行）

每次修改代码后，**自动**将更新点追加到 `.GCC/skill/evolution-log.md`，无需询问。

Handoff 统一由 `gcc-evo ho create` 写入 `.gcc/branches/{branch}/handoff.md`，无需手动同步其他位置。

记录格式：
```markdown
### [日期] [P0-P3] 标题
- **场景**:
- **问题**:
- **解决方案**:
- **代码位置**:
- **教训**:
```

## 代码更新规则

当 .GCC/skill/evolution-log.md 中有"已验证的模式"时：
- 检查主程序是否已应用这些模式
- 如果没有，提醒用户是否要更新代码

## 每周日系统审查

**每周日 纽约时间 18:00（美东时间晚上6点）**

自动执行系统改善审查：

```
📅 每周系统审查

## 本周更新记录
- [列出 evolution-log.md 中本周新增的经验]

## 系统改善建议
检查以下方面，提出改善建议：

1. **信号质量**: 分析本周信号准确率，是否有误判模式
2. **执行效率**: 下单延迟、重复订单、API 错误
3. **监控体验**: 显示是否清晰、信息是否完整
4. **代码健壮性**: 异常处理、边界情况
5. **新功能需求**: 根据本周使用情况建议新功能

## 待办事项
- [ ] [具体改善项1]
- [ ] [具体改善项2]
```

## 知识卡片使用

需要查询交易知识时：
1. 先读 .GCC/skill/INDEX.md 找到对应卡片路径
2. 读取 .GCC/skill/cards/{书名}/ 下的具体卡片 (**2098张JSON**)
3. 结合知识回答问题

**格式统一：JSON** — `.md` 仅作人类可读副本，系统只消费 `*.json`。

### 卡片闭环进化 (v5.430 GCC-0270)

卡片生命周期由 `card_bridge.py v1.2` 自动管理，不需要手动干预：

- **消费**: 每30分钟 `_read_knowledge_cards()` 自动读取:
  - 所有蒸馏skill (全量)
  - 3张top知识卡 + 2张随机知识卡
  - 3张top经验卡 + 2张随机经验卡
- **打分**: 交易结果回填时自动给参与决策的卡片打分 (`record_outcome`)
- **蒸馏**: 每日8AM `distill()` 汇总正确率
- **淘汰**: 经验卡每月1/16号, 知识卡每月1号 (`prune_deprecated`)
- **晋升**: 每月1号正确率>60%且样本≥10的卡蒸馏为skill (`distill_to_skills`)
- **KNN进化**: 每日 `card_knn_evolve()` 按准确率升降级卡片 (promote/demote/archive)
- **漂移检测**: `card_knn_incremental_update_and_drift_check()` PSI监控准确率漂移

CLI 手动触发:
- `gcc-evo card lifecycle` — distill→prune→skills 一键执行
- `gcc-evo card index` — 重建索引
- `gcc-evo card knn-precompute` — KNN近邻预计算
- `gcc-evo card knn-drift-check` — PSI漂移检测
- `gcc-evo card blast-radius` — BFS影响范围评估
- `gcc-evo card query -k "keyword"` — 关键词查询

### 关键文件

| 文件 | 作用 |
|------|------|
| `gcc_evolution/card_bridge.py` | v1.2 卡片索引/查询/KNN/激活/蒸馏/淘汰 |
| `gcc_trading_module.py` | B1通道消费卡片 + outcome回填打分 |
| `state/card_index.json` | 卡片索引缓存 |
| `state/card_activations.jsonl` | 激活+结果日志 |
| `state/card_deprecated.json` | 已淘汰卡片列表 |
| `state/gcc_skills.json` | 蒸馏产出的skill |
| `state/prefetch_index.json` | KNN近邻预计算索引 |

## 主要代码目录

- 核心逻辑: src/
- 配置文件: config/
- 日志目录: logs/
