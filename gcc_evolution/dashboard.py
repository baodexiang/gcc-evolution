"""
GCC v4.91 — Dashboard Base
通用 Streamlit 看板基类。

设计原则：
  引擎提供数据接口，用户继承后实现展示逻辑。
  不假设数据是什么领域，不知道"交易"是什么。
  用户只需实现 render() 方法。

使用方式：
  class MyDashboard(GccDashboard):
      def render(self):
          self.show_improvements()
          self.show_tasks()
          # 自己加业务图表
          data = self.db_query("SELECT * FROM my_source")
          st.line_chart(data)

  if __name__ == "__main__":
      MyDashboard().run()

启动：
  streamlit run dashboard.py
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GccDashboard:
    """
    GCC 通用看板基类。
    提供标准数据读取方法，用户继承后自定义展示。
    """

    title:    str = "GCC Dashboard"
    subtitle: str = "Agentic AI Evolution Engine"
    gcc_dir:  str = ".gcc"

    def __init__(self):
        self._db   = None
        self._duck = None

    # ── 启动 ──────────────────────────────────────────────

    def run(self):
        """启动 Streamlit 看板"""
        try:
            import streamlit as st
        except ImportError:
            print("请安装 streamlit: pip install streamlit")
            print("启动: streamlit run your_dashboard.py")
            return

        st.set_page_config(
            page_title=self.title,
            page_icon="⚡",
            layout="wide",
        )
        st.title(self.title)
        if self.subtitle:
            st.caption(self.subtitle)

        self._init_connections()
        self.render()

    def render(self):
        """
        子类实现此方法，填充看板内容。
        默认展示 GCC 系统概览。
        """
        self.show_system_overview()
        self.show_improvements()
        self.show_tasks()
        self.show_skillbank()

    # ── 标准组件 ──────────────────────────────────────────

    def show_system_overview(self):
        """系统状态概览"""
        try:
            import streamlit as st
            from gcc_evolution.state_manager import StateManager
            from gcc_evolution.scheduler import Scheduler

            col1, col2, col3, col4 = st.columns(4)

            sm  = StateManager(self.gcc_dir)
            sch = Scheduler(self.gcc_dir)
            due = sch.check_due()

            # 从数据库读统计
            conn = self._get_db()
            if conn:
                improvements = conn.execute(
                    "SELECT COUNT(*) as n FROM improvements"
                ).fetchone()
                tasks_active = conn.execute(
                    "SELECT COUNT(*) as n FROM tasks WHERE status IN ('running','paused')"
                ).fetchone()
                pending_sugs = conn.execute(
                    "SELECT COUNT(*) as n FROM suggestions WHERE status='pending'"
                ).fetchone()

                col1.metric("改善点", improvements["n"] if improvements else 0)
                col2.metric("活跃任务", tasks_active["n"] if tasks_active else 0)
                col3.metric("待审核建议", pending_sugs["n"] if pending_sugs else 0)
                col4.metric("到期定时任务", len(due),
                            delta="需要处理" if due else None,
                            delta_color="inverse" if due else "off")
        except Exception as e:
            import streamlit as st
            st.warning(f"概览加载失败: {e}")

    def show_improvements(self):
        """改善点列表"""
        try:
            import streamlit as st
            import pandas as pd

            st.subheader("改善点")
            conn = self._get_db()
            if not conn:
                st.info("数据库未连接"); return

            rows = conn.execute(
                "SELECT id, title, status, item_type FROM improvements ORDER BY id"
            ).fetchall()
            if not rows:
                st.info("暂无改善点数据"); return

            df = pd.DataFrame([dict(r) for r in rows])
            st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            import streamlit as st
            st.warning(f"改善点加载失败: {e}")

    def show_tasks(self):
        """任务状态"""
        try:
            import streamlit as st
            import pandas as pd

            st.subheader("任务")
            conn = self._get_db()
            if not conn:
                return

            rows = conn.execute("""
                SELECT title, status, progress, priority, updated_at
                FROM tasks
                WHERE status IN ('running','paused','pending')
                ORDER BY updated_at DESC
            """).fetchall()

            if not rows:
                st.info("无活跃任务")
                return

            df = pd.DataFrame([dict(r) for r in rows])
            st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            import streamlit as st
            st.warning(f"任务加载失败: {e}")

    def show_skillbank(self):
        """SkillBank 概况"""
        try:
            import streamlit as st
            from gcc_evolution.skill_registry import SkillBank

            st.subheader("SkillBank")
            sb = SkillBank(self.gcc_dir)
            s  = sb.status()

            col1, col2, col3 = st.columns(3)
            col1.metric("General Skills", s["general"])
            col2.metric("Task-Specific", s["task_specific"])
            col3.metric("平均置信度", f"{s['avg_confidence']:.0%}")
        except Exception as e:
            import streamlit as st
            st.warning(f"SkillBank 加载失败: {e}")

    # ── 数据访问 ──────────────────────────────────────────

    def db_query(self, sql: str) -> list[dict]:
        """直接查询 GCC 数据库，返回字典列表"""
        conn = self._get_db()
        if not conn:
            return []
        try:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("[DASHBOARD] db_query failed: %s", e)
            return []

    def duck_query(self, sql: str):
        """DuckDB 查询，返回 QueryResult"""
        from gcc_evolution.duckdb_adapter import DuckDbAdapter
        if not self._duck:
            self._duck = DuckDbAdapter(self.gcc_dir)
        return self._duck.query(sql)

    def get_state(self, key: str, default=None):
        """读取系统状态"""
        from gcc_evolution.state_manager import StateManager
        return StateManager(self.gcc_dir).get(key, default)

    # ── 内部 ──────────────────────────────────────────────

    def _init_connections(self):
        self._get_db()

    def _get_db(self):
        if self._db:
            return self._db
        try:
            import sqlite3
            from pathlib import Path
            db_path = Path(self.gcc_dir) / "gcc.db"
            if db_path.exists():
                self._db = sqlite3.connect(str(db_path))
                self._db.row_factory = sqlite3.Row
        except Exception as e:
            logger.warning("[DASHBOARD] database connection failed: %s", e)
        return self._db


# ── 示例看板（可直接运行）───────────────────────────────────

class DefaultDashboard(GccDashboard):
    """开箱即用的默认看板，继承并覆盖 render() 自定义"""

    title    = "GCC Evolution Dashboard"
    subtitle = "Agentic AI — Persistent Memory + Orchestrated Autonomy"

    def render(self):
        import streamlit as st

        tab1, tab2, tab3 = st.tabs(["📊 概览", "🎯 改善点", "⚙️ 任务"])

        with tab1:
            self.show_system_overview()
            st.divider()
            self.show_skillbank()

        with tab2:
            self.show_improvements()

        with tab3:
            self.show_tasks()


if __name__ == "__main__":
    DefaultDashboard().run()
