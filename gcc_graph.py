# gcc_graph.py — GCC 版本控制图引擎 v1.0
#
# 给 GCC 加上真正的 Git DAG 结构:
# - 每个 commit 有 id + parent 指针
# - branch 有 base_commit (分叉点)
# - merge 有两个 parent
# - graph 命令画 ASCII 分支图
#
# 数据文件: .GCC/graph.json (DAG 数据)
# 零依赖: 只用 Python 标准库
#
# 用法:
#   python gcc_graph.py log                          # 线性日志
#   python gcc_graph.py graph                        # ASCII 分支图
#   python gcc_graph.py graph --all                  # 包含已合并分支
#   python gcc_graph.py branches                     # 分支列表
#   python gcc_graph.py show <commit-id>             # 查看单个 commit
#   python gcc_graph.py status                       # 当前状态
#
# Agent 集成 (在 GCC COMMIT/BRANCH/MERGE 时自动调用):
#   from gcc_graph import GCCGraph
#   g = GCCGraph()
#   g.commit("Fix AUD-001")                          # 记录 commit
#   g.branch("feature/audit-fixes")                  # 创建分支
#   g.merge("feature/audit-fixes", "Merge audit")    # 合并分支
#   print(g.render_graph())                          # 画图

import json
import os
import hashlib
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

GCC_DIR = Path(".GCC")
GRAPH_FILE = GCC_DIR / "graph.json"

COLORS = {
    "main":    "\033[92m",   # 绿
    "branch1": "\033[93m",   # 黄
    "branch2": "\033[96m",   # 青
    "branch3": "\033[95m",   # 紫
    "branch4": "\033[91m",   # 红
    "merge":   "\033[97m",   # 白
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


class GCCGraph:
    """GCC 的 DAG 版本控制图"""

    def __init__(self, gcc_dir=None):
        self.gcc_dir = Path(gcc_dir) if gcc_dir else GCC_DIR
        self.graph_file = self.gcc_dir / "graph.json"
        self._check_nested()
        self.data = self._load()

    def _check_nested(self):
        """检测并自动修正嵌套 .GCC/"""
        current = self.gcc_dir.resolve()
        if not current.exists():
            return
        # 向上查找是否有更高层级的 .GCC/
        d = current.parent  # 项目根目录
        root_gcc = None
        while True:
            parent = d.parent
            if parent == d:
                break
            d = parent
            candidate = d / ".GCC"
            if candidate.exists() and candidate.is_dir() and candidate != current:
                root_gcc = candidate
        if root_gcc:
            root_dir = str(root_gcc.parent)
            print(f"\033[93m⚠️  检测到嵌套 .GCC/ — 自动迁移中...\033[0m")
            print(f"   当前: {current}")
            print(f"   根级: {root_gcc}")
            try:
                migrate_nested(root_dir)
                # 迁移后切换到根 .GCC/
                self.gcc_dir = root_gcc
                self.graph_file = root_gcc / "graph.json"
            except Exception as e:
                print(f"   \033[91m迁移失败: {e}\033[0m")
                print(f"   手动执行: python gcc_graph.py migrate-nested --root {root_dir}")

    def _load(self) -> dict:
        if self.graph_file.exists():
            with open(self.graph_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "commits": {},
            "branches": {"main": {"head": None, "base_commit": None, "created": _now(), "status": "active"}},
            "current_branch": "main",
            "head": None,
        }

    def _save(self):
        self.gcc_dir.mkdir(parents=True, exist_ok=True)
        with open(self.graph_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def _gen_id(self, summary: str) -> str:
        """生成短 hash ID"""
        raw = f"{_now()}{summary}{len(self.data['commits'])}"
        h = hashlib.sha1(raw.encode()).hexdigest()[:7]
        return h

    # ── 核心操作 ──

    def commit(self, summary: str, files_changed: list = None, agent: str = "") -> str:
        """
        记录一个 commit

        Returns: commit_id
        """
        branch = self.data["current_branch"]
        parent = self.data["branches"][branch]["head"]
        cid = self._gen_id(summary)

        self.data["commits"][cid] = {
            "id": cid,
            "summary": summary,
            "timestamp": _now(),
            "branch": branch,
            "parent": parent,            # 单 parent (普通 commit)
            "parent2": None,             # 第二 parent (merge commit)
            "is_merge": False,
            "files_changed": files_changed or [],
            "agent": agent,
        }

        self.data["branches"][branch]["head"] = cid
        self.data["head"] = cid
        self._save()
        return cid

    def branch(self, name: str) -> str:
        """
        创建分支，记录分叉点

        Returns: branch name
        """
        if name in self.data["branches"]:
            print(f"⚠️  分支已存在: {name}")
            return name

        current = self.data["current_branch"]
        base = self.data["branches"][current]["head"]

        self.data["branches"][name] = {
            "head": base,               # 继承当前 head
            "base_commit": base,        # 分叉点
            "parent_branch": current,
            "created": _now(),
            "status": "active",
        }
        self.data["current_branch"] = name
        self._save()
        return name

    def checkout(self, name: str):
        """切换分支"""
        if name not in self.data["branches"]:
            print(f"❌ 分支不存在: {name}")
            return
        self.data["current_branch"] = name
        self.data["head"] = self.data["branches"][name]["head"]
        self._save()

    def merge(self, source_branch: str, summary: str = "") -> str:
        """
        合并分支，创建 merge commit（双 parent）

        Returns: merge commit id
        """
        target = self.data["current_branch"]
        if source_branch not in self.data["branches"]:
            print(f"❌ 分支不存在: {source_branch}")
            return None

        parent1 = self.data["branches"][target]["head"]
        parent2 = self.data["branches"][source_branch]["head"]
        msg = summary or f"Merge {source_branch} → {target}"
        cid = self._gen_id(msg)

        self.data["commits"][cid] = {
            "id": cid,
            "summary": msg,
            "timestamp": _now(),
            "branch": target,
            "parent": parent1,
            "parent2": parent2,          # 双 parent!
            "is_merge": True,
            "merge_from": source_branch,
            "files_changed": [],
            "agent": "",
        }

        self.data["branches"][target]["head"] = cid
        self.data["branches"][source_branch]["status"] = "merged"
        self.data["head"] = cid
        self._save()
        return cid

    def abandon(self, branch_name: str):
        """标记分支为废弃"""
        if branch_name in self.data["branches"]:
            self.data["branches"][branch_name]["status"] = "abandoned"
            self._save()

    # ── 查询 ──

    def get_branch_commits(self, branch: str) -> list:
        """获取分支上的所有 commit（从 head 往回追溯到分叉点）"""
        if branch not in self.data["branches"]:
            return []
        head = self.data["branches"][branch]["head"]
        base = self.data["branches"][branch].get("base_commit")
        commits = []
        visited = set()
        cid = head
        while cid and cid not in visited:
            visited.add(cid)
            if cid in self.data["commits"]:
                commits.append(self.data["commits"][cid])
            if cid == base and branch != "main":
                break
            c = self.data["commits"].get(cid, {})
            cid = c.get("parent")
        return commits

    def get_all_commits_topo(self) -> list:
        """拓扑排序所有 commit（最新在前）"""
        commits = list(self.data["commits"].values())
        commits.sort(key=lambda c: c["timestamp"], reverse=True)
        return commits

    # ── 渲染 ASCII 图 ──

    def render_graph(self, show_all=False) -> str:
        """
        渲染 ASCII 分支图

        类似 git log --graph --oneline --all
        """
        # 收集活跃分支
        branches = {}
        for name, info in self.data["branches"].items():
            if show_all or info["status"] == "active" or name == "main":
                branches[name] = info

        if not self.data["commits"]:
            return "  (空项目，无 commit)"

        # 分配分支列（main 永远在第0列）
        branch_order = ["main"]
        for name in sorted(branches.keys()):
            if name != "main":
                branch_order.append(name)
        col_map = {name: i for i, name in enumerate(branch_order)}

        color_list = list(COLORS.values())
        branch_colors = {}
        for i, name in enumerate(branch_order):
            branch_colors[name] = color_list[i % len(color_list)]

        # 按时间排序所有 commit
        all_commits = self.get_all_commits_topo()

        # 找出每个 commit 所在的列
        def get_col(c):
            b = c.get("branch", "main")
            return col_map.get(b, 0)

        # 找出分叉和合并点
        branch_starts = {}  # commit_id → branch_name (分叉点)
        merge_points = {}   # commit_id → (from_col, to_col)

        for name, info in branches.items():
            if info.get("base_commit") and name != "main":
                branch_starts[info["base_commit"]] = name
        for c in all_commits:
            if c.get("is_merge") and c.get("merge_from"):
                src = c["merge_from"]
                if src in col_map:
                    merge_points[c["id"]] = (col_map[src], col_map.get(c["branch"], 0))

        # 渲染
        lines = []
        num_cols = len(branch_order)
        current_branch = self.data["current_branch"]

        # 标题
        lines.append(f"{BOLD}GCC Graph{RESET}")
        lines.append("")

        # 分支头标签
        header_parts = []
        for i, name in enumerate(branch_order):
            color = branch_colors[name]
            status = branches.get(name, {}).get("status", "")
            marker = " ★" if name == current_branch else ""
            s_mark = "" if status == "active" else f" ({status})"
            header_parts.append(f"{color}{name}{marker}{s_mark}{RESET}")
        lines.append("  ".join(header_parts))
        lines.append("")

        # 每个 commit 一行
        for c in all_commits:
            cid = c["id"]
            col = get_col(c)
            color = branch_colors.get(c.get("branch", "main"), COLORS["main"])
            is_head = (cid == self.data["branches"].get(c.get("branch", "main"), {}).get("head"))

            # 画管道
            pipes = []
            for i in range(num_cols):
                if i == col:
                    if c.get("is_merge"):
                        pipes.append(f"{COLORS['merge']}◆{RESET}")  # merge
                    elif is_head:
                        pipes.append(f"{color}●{RESET}")  # head
                    else:
                        pipes.append(f"{color}○{RESET}")  # normal
                else:
                    # 检查这列的分支在此时是否存在
                    bn = branch_order[i] if i < len(branch_order) else None
                    if bn and bn in branches:
                        b_head = branches[bn].get("head")
                        b_base = branches[bn].get("base_commit")
                        # 如果这个分支在这个时间点存在（head 在此 commit 之后，base 在此之前或等于）
                        if b_head and b_base:
                            head_ts = self.data["commits"].get(b_head, {}).get("timestamp", "")
                            base_ts = self.data["commits"].get(b_base, {}).get("timestamp", "")
                            if base_ts <= c["timestamp"] <= head_ts:
                                pipes.append(f"{branch_colors.get(bn, DIM)}│{RESET}")
                                continue
                    pipes.append(" ")

            pipe_str = " ".join(pipes)

            # 合并线
            merge_line = ""
            if cid in merge_points:
                from_c, to_c = merge_points[cid]
                if from_c > to_c:
                    merge_line = f"  {DIM}←─┘{RESET}"
                else:
                    merge_line = f"  {DIM}└─→{RESET}"

            # 分叉线
            fork_line = ""
            if cid in branch_starts:
                fork_branch = branch_starts[cid]
                fork_col = col_map.get(fork_branch, 0)
                if fork_col > col:
                    fork_line = f"  {branch_colors.get(fork_branch, DIM)}├─→ {fork_branch}{RESET}"

            # commit 信息
            ts_short = c["timestamp"][5:16] if len(c["timestamp"]) >= 16 else c["timestamp"]
            agent_str = f" [{c['agent']}]" if c.get("agent") else ""
            summary = c["summary"]
            if len(summary) > 45:
                summary = summary[:42] + "..."

            line = f"  {pipe_str}  {color}{cid}{RESET} {DIM}{ts_short}{RESET} {summary}{agent_str}{merge_line}{fork_line}"
            lines.append(line)

            # 分叉点下面画分叉
            if cid in branch_starts:
                fork_pipes = []
                for i in range(num_cols):
                    fork_bn = branch_order[i] if i < len(branch_order) else None
                    if i == col:
                        fork_pipes.append(f"{color}│{RESET}")
                    elif fork_bn == branch_starts[cid]:
                        fork_pipes.append(f"{branch_colors.get(fork_bn, DIM)}│{RESET}")
                    else:
                        fork_pipes.append(" ")
                lines.append(f"  {' '.join(fork_pipes)}")

        # 底部统计
        lines.append("")
        active = sum(1 for b in branches.values() if b["status"] == "active")
        merged = sum(1 for b in self.data["branches"].values() if b["status"] == "merged")
        total_c = len(self.data["commits"])
        lines.append(f"{DIM}  {total_c} commits, {active} active branches, {merged} merged{RESET}")

        return "\n".join(lines)

    def render_log(self, branch: str = None, limit: int = 20) -> str:
        """渲染线性日志（类似 git log --oneline）"""
        b = branch or self.data["current_branch"]
        commits = self.get_branch_commits(b)[:limit]
        color = COLORS.get("main")

        lines = []
        lines.append(f"{BOLD}GCC Log — {b}{RESET}")
        lines.append("")

        for c in commits:
            cid = c["id"]
            is_head = (cid == self.data["branches"].get(b, {}).get("head"))
            marker = f"{color}● {RESET}" if is_head else f"{DIM}○ {RESET}"
            merge_tag = f" {DIM}(merge){RESET}" if c.get("is_merge") else ""
            ts = c["timestamp"][5:16] if len(c["timestamp"]) >= 16 else c["timestamp"]

            lines.append(f"  {marker}{color}{cid}{RESET} {c['summary']}{merge_tag}")
            lines.append(f"       {DIM}{ts}{RESET}")

            if c.get("files_changed"):
                fc = c["files_changed"]
                if len(fc) <= 3:
                    lines.append(f"       {DIM}files: {', '.join(fc)}{RESET}")
                else:
                    lines.append(f"       {DIM}files: {', '.join(fc[:3])} +{len(fc)-3} more{RESET}")
            lines.append("")

        return "\n".join(lines)

    def render_branches(self) -> str:
        """渲染分支列表"""
        lines = []
        lines.append(f"{BOLD}GCC Branches{RESET}")
        lines.append("")

        current = self.data["current_branch"]
        for name, info in sorted(self.data["branches"].items()):
            marker = " ★" if name == current else "  "
            status = info["status"]
            head = info.get("head", "none")[:7] if info.get("head") else "empty"
            base = info.get("base_commit", "")[:7] if info.get("base_commit") else "root"
            parent = info.get("parent_branch", "")

            if status == "active":
                color = "\033[92m"
            elif status == "merged":
                color = "\033[90m"
            else:
                color = "\033[91m"

            commits = self.get_branch_commits(name)
            count = len(commits)
            from_str = f" (from {parent})" if parent and parent != "main" else ""

            lines.append(f"  {color}{marker} {name:<25} {status:<10} {count:>3} commits  head={head}  base={base}{from_str}{RESET}")

        lines.append("")
        return "\n".join(lines)

    def render_status(self) -> str:
        """渲染当前状态"""
        b = self.data["current_branch"]
        head = self.data.get("head", "none")
        head_commit = self.data["commits"].get(head, {})

        lines = []
        lines.append(f"{BOLD}GCC Status{RESET}")
        lines.append(f"  Branch: {b}")
        lines.append(f"  Head:   {head}")
        if head_commit:
            lines.append(f"  Last:   {head_commit.get('summary', '')}")
            lines.append(f"  Time:   {head_commit.get('timestamp', '')}")
        lines.append(f"  Total:  {len(self.data['commits'])} commits, {len(self.data['branches'])} branches")
        return "\n".join(lines)

    def show_commit(self, cid: str) -> str:
        """显示单个 commit 详情"""
        c = self.data["commits"].get(cid)
        if not c:
            # 尝试前缀匹配
            matches = [k for k in self.data["commits"] if k.startswith(cid)]
            if len(matches) == 1:
                c = self.data["commits"][matches[0]]
            else:
                return f"❌ 未找到 commit: {cid}"

        lines = []
        lines.append(f"{BOLD}Commit: {c['id']}{RESET}")
        lines.append(f"  Branch:    {c['branch']}")
        lines.append(f"  Time:      {c['timestamp']}")
        lines.append(f"  Summary:   {c['summary']}")
        lines.append(f"  Parent:    {c['parent'] or 'none (initial)'}")
        if c.get("parent2"):
            lines.append(f"  Parent2:   {c['parent2']} (merge from {c.get('merge_from', '?')})")
        if c.get("agent"):
            lines.append(f"  Agent:     {c['agent']}")
        if c.get("files_changed"):
            lines.append(f"  Files:     {', '.join(c['files_changed'])}")
        return "\n".join(lines)


# ── 迁移: 从旧 commit.md 导入 ──

def migrate_from_commit_md(gcc_dir: str = ".GCC") -> int:
    """
    从旧格式的 commit.md 导入到 graph.json

    解析 commit.md 中的:
      ## Commit: c1
      **Timestamp**: 2026-02-10T02:15:00Z
      **Summary**: xxx
    """
    gcc_path = Path(gcc_dir)
    g = GCCGraph(gcc_dir)
    imported = 0

    for branch_dir in (gcc_path / "branches").iterdir():
        if not branch_dir.is_dir():
            continue
        branch_name = branch_dir.name
        commit_file = branch_dir / "commit.md"
        if not commit_file.exists():
            continue

        # 确保分支存在
        if branch_name not in g.data["branches"]:
            g.data["branches"][branch_name] = {
                "head": None, "base_commit": None,
                "created": _now(), "status": "active"
            }

        # 解析 commit.md
        with open(commit_file, "r", encoding="utf-8") as f:
            content = f.read()

        import re
        # 找所有 commit 块
        pattern = r'## (?:Commit|Merge): (\S+)\s*\n\*\*Timestamp\*\*: (.+)\n\*\*Summary\*\*: (.+)'
        matches = re.findall(pattern, content)

        prev_id = None
        for old_id, timestamp, summary in matches:
            # 生成新 ID
            cid = hashlib.sha1(f"{timestamp}{summary}".encode()).hexdigest()[:7]

            is_merge = "Merge" in summary or "merge" in summary

            g.data["commits"][cid] = {
                "id": cid,
                "summary": summary.strip(),
                "timestamp": timestamp.strip(),
                "branch": branch_name,
                "parent": prev_id,
                "parent2": None,
                "is_merge": is_merge,
                "files_changed": [],
                "agent": "",
                "old_id": old_id,  # 保留旧 ID 映射
            }

            prev_id = cid
            imported += 1

        # 设置分支 head
        if prev_id:
            g.data["branches"][branch_name]["head"] = prev_id

    # 设置全局 head
    main_head = g.data["branches"].get("main", {}).get("head")
    if main_head:
        g.data["head"] = main_head

    g._save()
    print(f"✅ 迁移完成: {imported} 个 commit 从 commit.md 导入到 graph.json")
    return imported


def migrate_nested(root_dir: str) -> bool:
    """
    自动修正嵌套 .GCC/ — 迁移到根项目的 module/<name> 分支

    调用方式:
      python gcc_graph.py migrate-nested --root /path/to/project-root

    或被 Agent 在检测到嵌套时自动调用。
    """
    root = Path(root_dir).resolve()
    root_gcc = root / ".GCC"
    if not root_gcc.exists():
        print(f"❌ 根目录无 .GCC/: {root}")
        return False

    current = Path.cwd().resolve()
    current_gcc = current / ".GCC"
    if not current_gcc.exists():
        print(f"❌ 当前目录无 .GCC/: {current}")
        return False

    if current_gcc == root_gcc:
        print("⚠️  当前目录就是根项目，无需迁移")
        return False

    # 计算模块名
    try:
        rel = current.relative_to(root)
        module_name = str(rel).replace(os.sep, "-").replace("/", "-")
    except ValueError:
        module_name = current.name

    print(f"🔄 迁移嵌套 .GCC/")
    print(f"   从: {current_gcc}")
    print(f"   到: {root_gcc} → module/{module_name}")

    # 1. 在根项目创建 module 分支
    root_graph = GCCGraph(str(root_gcc))
    branch_name = f"module/{module_name}"

    if branch_name not in root_graph.data["branches"]:
        # 保存当前分支，切到 main 创建分支
        saved_branch = root_graph.data["current_branch"]
        root_graph.data["current_branch"] = "main"
        root_graph.branch(branch_name)
        root_graph.data["current_branch"] = saved_branch
        root_graph._save()

    # 2. 合并 commit 历史
    nested_branches_dir = current_gcc / "branches"
    if nested_branches_dir.exists():
        for bdir in nested_branches_dir.iterdir():
            if not bdir.is_dir():
                continue
            # 复制 commit.md 内容
            src_commit = bdir / "commit.md"
            if src_commit.exists():
                # 目标分支目录
                target_branch_dir = root_gcc / "branches" / branch_name.replace("/", "-")
                target_branch_dir.mkdir(parents=True, exist_ok=True)

                target_commit = target_branch_dir / "commit.md"
                with open(src_commit, "r", encoding="utf-8") as f:
                    content = f.read()

                mode = "a" if target_commit.exists() else "w"
                with open(target_commit, mode, encoding="utf-8") as f:
                    f.write(f"\n\n== Migrated from nested .GCC/ ({current}) ==\n")
                    f.write(content)

                # 复制 log.md
                src_log = bdir / "log.md"
                if src_log.exists():
                    target_log = target_branch_dir / "log.md"
                    with open(src_log, "r", encoding="utf-8") as f:
                        log_content = f.read()
                    mode = "a" if target_log.exists() else "w"
                    with open(target_log, mode, encoding="utf-8") as f:
                        f.write(f"\n\n== Migrated from {current} ==\n")
                        f.write(log_content)

                # 复制 metadata.yaml
                src_meta = bdir / "metadata.yaml"
                if src_meta.exists():
                    target_meta = target_branch_dir / "metadata.yaml"
                    if not target_meta.exists():
                        import shutil
                        shutil.copy2(src_meta, target_meta)

    # 3. 导入 graph.json（如果有）
    nested_graph = current_gcc / "graph.json"
    if nested_graph.exists():
        with open(nested_graph, "r", encoding="utf-8") as f:
            ng = json.load(f)
        # 将嵌套的 commit 加入根 graph，标记来源
        for cid, commit in ng.get("commits", {}).items():
            new_cid = f"n{cid}"  # 加前缀避免冲突
            commit["id"] = new_cid
            commit["branch"] = branch_name
            commit["_migrated_from"] = str(current)
            # 修正 parent 引用
            if commit.get("parent"):
                commit["parent"] = f"n{commit['parent']}"
            if commit.get("parent2"):
                commit["parent2"] = f"n{commit['parent2']}"
            root_graph.data["commits"][new_cid] = commit
        root_graph._save()

    # 4. 记录迁移到根 log
    root_log = root_gcc / "branches" / "main" / "log.md"
    if root_log.exists():
        with open(root_log, "a", encoding="utf-8") as f:
            f.write(f"\n## Migration — {_now()}\n")
            f.write(f"**Action**: Migrated nested .GCC/ from `{current}` to `{branch_name}` branch\n")
            f.write(f"**Reason**: Nested .GCC/ detected, consolidated to maintain single project graph\n\n")

    # 5. 删除嵌套 .GCC/
    import shutil
    shutil.rmtree(current_gcc)
    print(f"   ✅ 已迁移到 {branch_name} 分支")
    print(f"   ✅ 已删除 {current_gcc}")
    print(f"   📊 运行 `cd {root} && python gcc_graph.py graph --all` 查看完整图")
    return True


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── CLI ──

def main():
    p = argparse.ArgumentParser(description="GCC Graph — 版本控制图 v1.0")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("graph", help="ASCII 分支图").add_argument("--all", action="store_true")
    pl = sub.add_parser("log", help="线性日志")
    pl.add_argument("--branch", default=None)
    pl.add_argument("-n", type=int, default=20)
    sub.add_parser("branches", help="分支列表")
    sub.add_parser("status", help="当前状态")
    ps = sub.add_parser("show", help="查看 commit")
    ps.add_argument("id")
    sub.add_parser("migrate", help="从旧 commit.md 导入")
    pmn = sub.add_parser("migrate-nested", help="修正嵌套 .GCC/")
    pmn.add_argument("--root", required=True, help="根项目路径")

    # Demo: 快速演示
    sub.add_parser("demo", help="生成演示数据")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return

    if args.cmd == "demo":
        _run_demo()
        return

    if args.cmd == "migrate":
        migrate_from_commit_md()
        return

    if args.cmd == "migrate-nested":
        migrate_nested(args.root)
        return

    g = GCCGraph()

    if args.cmd == "graph":
        print(g.render_graph(show_all=args.all))
    elif args.cmd == "log":
        print(g.render_log(branch=args.branch, limit=args.n))
    elif args.cmd == "branches":
        print(g.render_branches())
    elif args.cmd == "status":
        print(g.render_status())
    elif args.cmd == "show":
        print(g.show_commit(args.id))


def _run_demo():
    """生成演示数据展示分支图效果"""
    import shutil
    demo_dir = Path(".GCC_demo")
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    demo_dir.mkdir()

    g = GCCGraph(demo_dir)

    # main 上初始提交
    c1 = g.commit("Initial scaffold — Flask app + models + tests")
    c2 = g.commit("Add signal CRUD endpoints", files_changed=["blueprints/signals.py", "services/signal_service.py"])
    c3 = g.commit("Add 3Commas client integration", files_changed=["clients/three_commas.py"])

    # 创建分支: feature/audit-fixes
    g.branch("feature/audit-fixes")
    c4 = g.commit("Fix AUD-001: trailing stop checks x4 direction", files_changed=["price_scan_engine.py"])
    c5 = g.commit("Fix AUD-004: adjust stop-loss threshold", files_changed=["price_scan_engine.py"])

    # 切回 main，继续开发
    g.checkout("main")
    c6 = g.commit("Add Schwab client", files_changed=["clients/schwab.py"])

    # 创建另一个分支: feature/monitor-panel
    g.branch("feature/monitor-panel")
    c7 = g.commit("Add improvement tracker panel to monitor", files_changed=["monitor.py"])
    c8 = g.commit("Add color coding for P0/P1/P2", files_changed=["monitor.py"])

    # 切回 main，合并 audit-fixes
    g.checkout("main")
    g.merge("feature/audit-fixes", "Merge audit fixes — AUD-001 + AUD-004 resolved")

    # 继续 main
    c10 = g.commit("Update config for production deploy", files_changed=["config.py"])

    # 合并 monitor-panel
    g.merge("feature/monitor-panel", "Merge monitor panel — improvement tracker integrated")

    # 最终 commit
    c12 = g.commit("v2.0 release — all audit items resolved")

    print(g.render_graph(show_all=True))
    print()
    print(g.render_branches())
    print()
    print(g.render_log(limit=5))

    # 清理
    shutil.rmtree(demo_dir)
    print(f"\n{DIM}(demo data cleaned up){RESET}")


if __name__ == "__main__":
    main()
