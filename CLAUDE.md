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
2. 读取 .GCC/skill/cards/ 下的具体卡片
3. 结合知识回答问题

## 主要代码目录

- 核心逻辑: src/
- 配置文件: config/
- 日志目录: logs/
