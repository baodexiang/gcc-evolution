"""
GCC v4.91 — DuckDB Adapter
通用数据查询适配器。

设计原则：
  引擎不知道数据是什么领域。
  用户注册数据源（文件路径/格式），引擎负责查询和聚合。
  支持 jsonl / parquet / csv / sqlite。

使用方式：
  db = DuckDbAdapter()
  db.register_source("events", "logs/server.log", format="jsonl")
  db.register_source("history", "data/*.parquet", format="parquet")

  result = db.query("SELECT source_id, COUNT(*) FROM events GROUP BY source_id")
  summary = db.period_summary("events", hours=12)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DataSource:
    """注册的数据源"""
    name:        str
    path:        str            # 文件路径，支持 glob（data/*.parquet）
    format:      str            # jsonl / parquet / csv / sqlite
    time_field:  str = ""       # 时间字段名，用于 period 查询
    description: str = ""
    registered_at: str = field(default_factory=_now)


@dataclass
class QueryResult:
    """查询结果"""
    sql:         str
    rows:        list[dict]
    row_count:   int
    duration_ms: int
    error:       str = ""

    def to_df(self):
        """转 pandas DataFrame（需要 pandas）"""
        import pandas as pd
        return pd.DataFrame(self.rows)

    def first(self) -> dict:
        return self.rows[0] if self.rows else {}

    def column(self, name: str) -> list:
        return [r.get(name) for r in self.rows]


class DuckDbAdapter:
    """
    通用 DuckDB 查询适配器。
    用户注册数据源，引擎负责查询，不假设数据结构。
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self._sources: dict[str, DataSource] = {}
        self._conn = None
        self._load_sources()
        self._init_conn()

    # ── 连接 ──────────────────────────────────────────────

    def _init_conn(self):
        try:
            import duckdb
            self._conn = duckdb.connect()
            # 注册已有数据源
            for name, src in self._sources.items():
                self._register_view(name, src)
        except ImportError:
            self._conn = None

    def _register_view(self, name: str, src: DataSource):
        if not self._conn:
            return
        try:
            path = src.path
            if src.format == "jsonl":
                self._conn.execute(f"""
                    CREATE OR REPLACE VIEW {name} AS
                    SELECT * FROM read_json_auto('{path}',
                        format='newline_delimited',
                        ignore_errors=true)
                """)
            elif src.format == "parquet":
                self._conn.execute(f"""
                    CREATE OR REPLACE VIEW {name} AS
                    SELECT * FROM read_parquet('{path}')
                """)
            elif src.format == "csv":
                self._conn.execute(f"""
                    CREATE OR REPLACE VIEW {name} AS
                    SELECT * FROM read_csv_auto('{path}')
                """)
            elif src.format == "sqlite":
                # sqlite 需要 attach
                self._conn.execute(f"ATTACH '{path}' AS {name}_db (TYPE SQLITE)")
        except Exception as e:
            logger.warning("[DUCKDB] failed to register view '%s': %s", name, e)

    # ── 数据源注册 ────────────────────────────────────────

    def register_source(self, name: str, path: str,
                        format: str = "jsonl",
                        time_field: str = "",
                        description: str = "") -> DataSource:
        """注册数据源"""
        src = DataSource(
            name=name, path=path, format=format,
            time_field=time_field, description=description,
        )
        self._sources[name] = src
        self._save_sources()
        if self._conn:
            self._register_view(name, src)
        return src

    def unregister_source(self, name: str):
        if name in self._sources:
            del self._sources[name]
            self._save_sources()

    def list_sources(self) -> list[DataSource]:
        return list(self._sources.values())

    # ── 查询 ──────────────────────────────────────────────

    def query(self, sql: str) -> QueryResult:
        """执行任意 SQL，返回结构化结果"""
        import time
        start = time.time()

        if not self._conn:
            return QueryResult(sql=sql, rows=[], row_count=0,
                               duration_ms=0, error="DuckDB 未安装，请 pip install duckdb")
        try:
            rel  = self._conn.execute(sql)
            cols = [d[0] for d in rel.description]
            rows = [dict(zip(cols, row)) for row in rel.fetchall()]
            ms   = int((time.time() - start) * 1000)
            return QueryResult(sql=sql, rows=rows, row_count=len(rows), duration_ms=ms)
        except Exception as e:
            ms = int((time.time() - start) * 1000)
            return QueryResult(sql=sql, rows=[], row_count=0, duration_ms=ms, error=str(e))

    def period_summary(self, source_name: str,
                       hours: int = 24,
                       group_by: str = "",
                       count_field: str = "*") -> QueryResult:
        """
        通用时间段聚合查询。
        用户指定分组字段，引擎生成 SQL。

        参数：
          source_name  已注册的数据源名
          hours        回看时间窗口
          group_by     按哪个字段分组（为空则不分组）
          count_field  计数字段
        """
        src = self._sources.get(source_name)
        if not src:
            return QueryResult(sql="", rows=[], row_count=0,
                               duration_ms=0, error=f"数据源 {source_name} 未注册")

        time_filter = ""
        if src.time_field:
            time_filter = f"WHERE {src.time_field} >= NOW() - INTERVAL {hours} HOURS"

        if group_by:
            sql = f"""
                SELECT {group_by},
                       COUNT({count_field}) as count
                FROM {source_name}
                {time_filter}
                GROUP BY {group_by}
                ORDER BY count DESC
            """
        else:
            sql = f"SELECT COUNT({count_field}) as count FROM {source_name} {time_filter}"

        return self.query(sql.strip())

    def schema(self, source_name: str) -> list[dict]:
        """查看数据源的字段结构"""
        result = self.query(f"DESCRIBE {source_name}")
        return result.rows

    def sample(self, source_name: str, n: int = 5) -> QueryResult:
        """采样查看数据"""
        return self.query(f"SELECT * FROM {source_name} LIMIT {n}")

    # ── 持久化数据源配置 ──────────────────────────────────

    def _save_sources(self):
        data = {}
        for name, src in self._sources.items():
            data[name] = {
                "path":          src.path,
                "format":        src.format,
                "time_field":    src.time_field,
                "description":   src.description,
                "registered_at": src.registered_at,
            }
        f = self.gcc_dir / "duckdb_sources.json"
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_sources(self):
        f = self.gcc_dir / "duckdb_sources.json"
        if not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for name, v in data.items():
                self._sources[name] = DataSource(
                    name=name,
                    path=v.get("path", ""),
                    format=v.get("format", "jsonl"),
                    time_field=v.get("time_field", ""),
                    description=v.get("description", ""),
                    registered_at=v.get("registered_at", _now()),
                )
        except Exception as e:
            logger.warning("[DUCKDB] failed to load data sources config: %s", e)
