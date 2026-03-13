"""
key009_audit.py — KEY-009 日志审计
====================================
扫描server.log，按GCC任务+核心交易模块汇总表现，输出JSON供dashboard读取。
分析维度:
  1) GCC任务事件统计
  2) 外挂运行分析 (VF过滤/KNN抑制/L2_MACD触发执行)
  3) BrooksVision形态分析 (信号/评估/准确率)
  4) Vision Pre-filter逐品种拦截分析
  5) 门控拦截分析 (KEY-001/002/N_GATE/ANTI-CHEAT)
  6) 风险检测 + 改善建议

用法:
  python key009_audit.py                         # 默认12小时, 输出报告
  python key009_audit.py --hours 24              # 自定义窗口
  python key009_audit.py --json                  # 输出JSON到stdout
  python key009_audit.py --export                # 写入 state/key009_audit.json
  python key009_audit.py --loop                  # 每5分钟循环导出(供dashboard)
"""

import re
import json
import time
import argparse
import importlib
import io
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from zoneinfo import ZoneInfo

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

NY_TZ = ZoneInfo("America/New_York")
ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
EXPORT_FILE = STATE_DIR / "key009_audit.json"
EXPORT_FALLBACK_FILE = STATE_DIR / "key009_audit.latest.json"
logger = logging.getLogger(__name__)


def _write_key009_cache(payload: dict, *, indent=None):
    """写 KEY-009 缓存，主文件被占用时自动回退到备用文件。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=indent)
    errors = []
    for path in (EXPORT_FILE, EXPORT_FALLBACK_FILE):
        try:
            path.write_text(data, encoding="utf-8")
            return path
        except Exception as e:
            errors.append(f"{path.name}: {e}")
    raise PermissionError(" | ".join(errors))

# ============================================================
# KEY-009 GCC任务 → 日志标签映射
# ============================================================
TASK_TAGS = {
    "GCC-0171": {
        "name": "Vision Pre-filter 拦截准确率",
        "tags": ["[GCC-0171]", "[VF_ACC]", "[VF_EVAL]"],
        "expect_per_4h": 0,  # VF准确率回填依赖数据积累,无事件时不告警
    },
    "GCC-0172": {
        "name": "BrooksVision 形态准确率",
        "tags": ["[GCC-0172]", "[BV_ACC]"],
        "expect_per_4h": 0,
    },
    "GCC-0173": {
        "name": "MACD背离胜率追踪",
        "tags": ["[GCC-0173]"],
        "expect_per_4h": 1,
    },
    "GCC-0174": {
        "name": "知识卡活化 CardBridge",
        "tags": ["[GCC-0174]", "[CARD-BRIDGE]"],
        "expect_per_4h": 2,
    },
    "GCC-0193": {
        "name": "KNN模块审计",
        "tags": ["[KEY-007][BACKFILL]", "[KEY-007][CROSS_KNN]"],
        "expect_per_4h": 1,
    },
    "GCC-0197": {
        "name": "扫描引擎外挂审计",
        "tags": ["[GCC-0197]"],
        "expect_per_4h": 0,
    },
    "KEY-005-NC": {
        "name": "Agentic Nowcasting",
        "tags": ["[KEY-005][NC]"],
        "expect_per_4h": 0,
    },
    "KEY-011": {
        "name": "GCC交易决策模块 (PUCT树搜索)",
        "tags": ["[GCC-TRADE]", "[GCC-TM]"],
        "expect_per_4h": 0,
    },
}

# 关键数字提取 (GCC任务)
METRIC_PATTERNS = [
    (r"\[VF_ACC\].*acc=([0-9.]+)", "vf_acc"),
    (r"\[GCC-0172\]\[REVIEW\].*降级(\d+)项.*恢复(\d+)项", "bv_review"),
    (r"\[GCC-0173\]\[BACKFILL\].*回填(\d+)条", "macd_backfill"),
    (r"\[CARD-BRIDGE\]\[DISTILL\].*(\d+)卡.*validated=(\d+).*flagged=(\d+)", "card_distill"),
    (r"\[KEY-007\]\[BACKFILL\].*?(\d+)条", "knn_backfill"),
    (r"\[KEY-005\]\[NC\].*scored=(\d+).*hit_rate=([0-9.]+|N/A)", "nc_result"),
    (r"\[GCC-TRADE\]\s+\S+\s+action=(\w+)\s+verdict=(\w+)\s+consensus=(\d)/3", "gcctm_decision"),
    (r"\[GCC-TM\]\s+\S+\s+gcc=(\w+)\s+main=(\w+)\s+verdict=(\w+)", "gcctm_observe"),
    (r"\[GCC-TRADE\]\s+backfill\s+\S+:\s+(\d+)\s+outcomes filled", "gcctm_backfill"),
]

# ============================================================
# 核心模块分析 — 正则模式
# ============================================================

# 外挂VF过滤: [VF] PLTR plugin=SuperTrend dir=BUY filter=0.35 rel_vol=1.20
# filter值可能是数字(0.35)或字符串(REJECT/PASS)
RE_VF = re.compile(r"\[VF\]\s+(\S+)\s+plugin=(\S+)\s+dir=(\w+)\s+filter=(\S+)\s+rel_vol=(\S+)")

# L2 MACD背离
RE_MACD_TRIGGER = re.compile(r"\[L2_MACD\]\[trigger\]\s+(\S+)\s+(\w+)")
RE_MACD_REJECT = re.compile(r"\[L2_MACD\]\[reject\]\s+(\S+)")
RE_MACD_FINAL = re.compile(r"\[L2_MACD\]\[final\]\s+(\S+)\s+(\w+)\s+(执行成功|被门控拦截|订单发送失败)")

# KNN抑制: [PLUGIN_KNN][抑制] PLTR SuperTrend BUY ← KNN反向bear
RE_KNN_SUPPRESS = re.compile(r"\[PLUGIN_KNN\]\[抑制\]\s+(\S+)\s+(\S+)\s+(\w+)")

# 外挂信号执行: [v3.651] 外挂信号成功/冷却/门控拦截/失败: PLTR BUY bias=...
RE_PLUGIN_EXEC = re.compile(r"\[v3\.\d+\]\s+外挂信号(成功|冷却|门控拦截|失败):\s+(\S+)\s+(\w+)")

# KEY-004治理: [KEY-004][GOVERNANCE] symbol 外挂name score=x → action
RE_GOVERNANCE = re.compile(r"\[KEY-004\]\[GOVERNANCE\]\s+(\S+)\s+外挂(\S+)\s+score=([0-9.]+).*→\s*(\S+)")

# KEY-004外挂事件(scan engine): [KEY-004][PLUGIN_EVENT] phase=dispatch symbol=X source=ChanBS action=BUY
RE_PLUGIN_EVENT = re.compile(r"\[KEY-004\]\[PLUGIN_EVENT\]\s+phase=(\w+)\s+symbol=(\S+)\s+source=(\S+)\s+action=(\w+)\s+executed=(\S+)(?:\s+reason=(.*?))?(?:\s+price=(\S+))?$")

# 扫描引擎外挂扫描: [SYMBOL] PluginName: 扫描完成, 模式=xxx (非触发) / 未激活 / 无触发信号
# 日志中外挂名为中文(飞云/缠论BS/剥头皮)或英文(SuperTrend/RobHoffman)
RE_SCAN_PLUGIN = re.compile(r"\[(\S+)\]\s+(SuperTrend|RobHoffman|ChanBS|缠论BS|Chandelier|VisionPattern|飞云|Feiyun|DoublePattern|ComputeSignal|剥头皮):\s+扫描完成")

# P0路径外挂触发(不走扫描引擎, 直接发P0信号):
# [移动止损] COIN SELL 触发!  /  [移动止盈] HIMS BUY 触发!
RE_P0_TRAILING = re.compile(r"\[(移动止损|移动止盈)\]\s+(\S+)\s+(\w+)\s+触发!")
# [VisionPattern] SOL-USD 形态触发BUY!
RE_P0_VISION = re.compile(r"\[VisionPattern\]\s+(\S+)\s+形态触发(\w+)!")
# [GCC-0047] BTCUSDC BrooksVision触发  /  [GCC-0047] OPEN N字结构触发
RE_P0_GCC47 = re.compile(r"\[GCC-0047\]\s+(\S+)\s+(BrooksVision|N字结构)触发")

# BrooksVision (P0信号从[P0收到]计数, GCC-0047为备选)
RE_BV_P0 = re.compile(r"\[P0收到\]\s+(\S+)\s+(BUY|SELL)\s+BrooksVision")
RE_BV_GATE = re.compile(r"\[GCC-0172\]\[BV_GATE\]\s+(\S+)\s+\[(\w+)\]")
RE_BV_EVAL = re.compile(r"\[GCC-0172\]\[BV_EVAL\]\s+(\S+)\s+(\w+)\s+(\w+)\s+→\s+(CORRECT|INCORRECT|NEUTRAL)")

# Vision方向过滤(L2主循环, 旧格式兼容): [VISION_FILTER][拦截] SYMBOL ACTION: reason
RE_VISION_FILTER = re.compile(r"\[VISION_FILTER\]\[拦截\]\s+(\S+)\s+(\w+):\s+(.*)")
# GCC-0194新格式: [FILTER_CHAIN拦截] SYMBOL ACTION by REASON reason=TEXT
# server.log格式: "by volume reason=..." (空格分隔)
# scan engine格式: "by=volume struct=X/Y size=Z reason=..." (=分隔)
RE_FILTER_CHAIN_BLOCK = re.compile(r"\[FILTER_CHAIN拦截\]\s+(\S+)\s+(\w+)\s+by[= ](\S+).*?reason=(.*)")
RE_FILTER_CHAIN = re.compile(r"\[FILTER_CHAIN\]\s+(\S+)\s+(\w+)\s+passed=(True|False)")

# 门控拦截
RE_GATE_K1 = re.compile(r"\[KEY-001\]\[GATE\]\[拦截\]\s+(\S+)\s+(\w+)")
RE_GATE_K2 = re.compile(r"\[KEY-002\]\[GATE\]\[拦截\]\s+(\S+)\s+(\w+)")
RE_GATE_NGATE = re.compile(r"\[N_GATE拦截\]\s+(\S+)|\[N_GATE\]\[拦截\]\s+(\S+)")
RE_GATE_ANTICHEAT = re.compile(r"\[KEY-005\]\[ANTI-CHEAT\]\[BLOCK\]\s+(\S+)\s+(\w+)")
RE_GATE_ANCHOR = re.compile(r"\[KEY001-ANCHOR\]\[拦截\]\s+(\S+)\s+(\w+)")
RE_GATE_MASTER = re.compile(r"\[KEY001-MASTER\]\[OBS\]\s+(\S+)\s+(\w+)")
RE_GATE_VCACHE = re.compile(r"\[KEY001-VCACHE\]\[拦截\]\s+(\S+)\s+(\w+)")
RE_GATE_VALUE = re.compile(r"\[KEY-003\]\[VALUE-GUARD\]\[拦截\]\s+(\S+)")
RE_GATE_STALE = re.compile(r"\[DATA_STALE_BLOCK\]\[(\S+)\]")

# 基准K线门控: [P0][BASELINE] SYMBOL BUY/SELL 通过/拦截/未找到
RE_BASELINE = re.compile(r"\[P0\]\[BASELINE\]\s+(\S+)\s+(BUY|SELL)\s+(.*)")

# ── 新增: 5个遗漏日志解析 ──
# macd_divergence.log: ===== DATE SYMBOL =====
RE_MACD_DIV_HEADER = re.compile(r"=====\s+\d{4}-\d{2}-\d{2}\s+[\d:]+\s+(\S+)\s+=====")
RE_MACD_DIV_MODE = re.compile(r"模式:\s+(SIGNAL_FOUND|FILTERED)")
RE_MACD_DIV_FILTER = re.compile(r"过滤:\s+(.+)")
RE_MACD_DIV_STRENGTH = re.compile(r"强度:\s+([\d.]+)%")

# rob_hoffman_plugin.log
RE_RH_ER = re.compile(r"KAMA ER=([\d.]+)\s+.*阈值=([\d.]+)")
RE_RH_FILTERED = re.compile(r"\[(\S+)\]\s+FILTERED:\s+(.+)")
RE_RH_SIGNAL = re.compile(r"\[(\S+)\]\s+SIGNAL:\s+(\w+)")

# l1_module_diagnosis.log
RE_L1_HEADER = re.compile(r"=====\s+\d{4}-\d{2}-\d{2}\s+[\d:]+\s+(\S+)\s+=====")
RE_L1_DECISION = re.compile(r"L1综合:\s+(\w+)")

# value_analysis.log
RE_VA_FALLBACK = re.compile(r"\[KEY-003\]\[LIVE\]\[FALLBACK\]\s+ticker=(\S+)\s+reason=(.+?)(?:\s*->|$)")
RE_VA_BATCH = re.compile(r"\[KEY-003\]\[BATCH\].*?symbols=(\d+)\s+failed=(\d+)\s+status=(\w+)")


def parse_timestamp(line: str):
    """从日志行提取时间戳。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})", line)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def _is_crypto_symbol_like(sym: str) -> bool:
    s = (sym or "").upper()
    return s.endswith("USDC") or s.endswith("-USD")


def audit(log_path: str, hours: int = 12, check_coverage: bool = False) -> dict:
    """扫描日志，按GCC任务+核心模块汇总。支持逗号分隔的多个日志文件。
    check_coverage: True=做品种覆盖率检查(每天8am slot用)"""
    _now_ny = datetime.now(NY_TZ)
    cutoff = (_now_ny - timedelta(hours=hours)).replace(tzinfo=None)  # naive for log comparison
    now_str = _now_ny.strftime("%Y-%m-%d %H:%M ET")

    # GCC任务统计
    tasks = {}
    for task_id, info in TASK_TAGS.items():
        tasks[task_id] = {
            "name": info["name"],
            "count": 0,
            "errors": 0,
            "recent": [],
            "expect": info["expect_per_4h"],
        }

    metrics = defaultdict(list)

    # ── 核心模块统计 ──
    vf_by_plugin = defaultdict(lambda: defaultdict(int))
    vf_by_symbol = defaultdict(int)
    vf_total = 0

    macd_stats = {"trigger": 0, "reject": 0, "execute": 0, "gate_block": 0, "by_symbol": defaultdict(lambda: {"trigger": 0, "execute": 0})}

    knn_suppress = defaultdict(lambda: defaultdict(int))
    knn_suppress_total = 0

    plugin_exec = {"sent": 0, "skip": 0, "block": 0, "buy": 0, "sell": 0}

    governance_actions = defaultdict(int)

    # 扫描引擎外挂运行: {plugin: {scan: N, trigger: N, dispatch: N, executed: N, blocked: N}}
    scan_plugins = defaultdict(lambda: {"scan": 0, "trigger": 0, "dispatch": 0, "executed": 0, "blocked": 0, "block_reasons": defaultdict(int), "by_symbol": defaultdict(lambda: {"scan": 0, "trigger": 0})})

    # GCC-0197: 外挂dispatch事件(含价格), 供4H回填准确率
    plugin_signals = []

    bv_stats = {"signals": 0, "executed": 0, "gate_obs": 0,
                "eval": {"CORRECT": 0, "INCORRECT": 0, "NEUTRAL": 0},
                "patterns": defaultdict(int),
                "by_direction": {"BUY": 0, "SELL": 0}}

    # Vision方向过滤(L2主循环, [VISION_FILTER][拦截])
    vision_filter = {"total": 0, "by_symbol": defaultdict(int), "by_reason": defaultdict(int)}

    # ── 新增5日志统计 ──
    arbiter = {"total": 0, "by_signal": defaultdict(int), "by_symbol": defaultdict(lambda: defaultdict(int))}
    macd_div = {"found": 0, "filtered": 0, "filter_reasons": defaultdict(int), "strengths": []}
    _macd_div_cur_sym = None  # 当前文本块的品种
    rh_stats = {"scans": 0, "signals": 0, "filtered": 0, "er_below": 0, "filter_reasons": defaultdict(int)}
    l1_stats = {"total": 0, "by_signal": defaultdict(int)}
    va_stats = {"fallback": 0, "fallback_reasons": defaultdict(int), "batch_total": 0, "batch_failed": 0}

    gates = {
        "KEY-001": defaultdict(int),
        "KEY-002": defaultdict(int),
        "N_GATE": defaultdict(int),
        "ANTI-CHEAT": defaultdict(int),
        "ANCHOR": defaultdict(int),
        "MASTER-OBS": defaultdict(int),
        "VCACHE": defaultdict(int),
        "VALUE-GUARD": defaultdict(int),
        "DATA-STALE": defaultdict(int),
    }
    gate_totals = defaultdict(int)

    baseline_stats = {"total": 0, "pass": 0, "block": 0, "no_data": 0,
                      "by_symbol": defaultdict(lambda: {"pass": 0, "block": 0, "no_data": 0}),
                      "by_direction": defaultdict(lambda: {"pass": 0, "block": 0, "no_data": 0})}
    dc_stats = {"total": 0, "pass": 0, "block": 0, "no_data": 0}

    # 支持多日志文件(逗号分隔)
    log_paths = [p.strip() for p in log_path.split(",") if p.strip()]
    all_log_files = [Path(p) for p in log_paths if Path(p).exists()]

    if not all_log_files:
        return _build_result(now_str, hours, tasks, {}, {}, macd_stats, {}, 0,
                             plugin_exec, governance_actions, bv_stats, gates, gate_totals, [])

    for log_file in all_log_files:
      _last_ts = None  # 无时间戳行继承上一行的时间戳
      # 预扫描: 检查日志中是否有cutoff之后的时间戳
      # 如果没有(如log_to_server缺少时间戳), 则不做cutoff过滤, 全量计入
      _has_recent_ts = False
      try:
          with open(log_file, "r", encoding="utf-8", errors="ignore") as _pf:
              for _pl in _pf:
                  _pts = parse_timestamp(_pl)
                  if _pts and _pts >= cutoff:
                      _has_recent_ts = True
                      break
      except OSError:
          continue  # 文件损坏/锁定/OneDrive占位符→跳过此日志
      _past_cutoff = not _has_recent_ts  # 无近期时间戳→全量模式
      with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
          try:
            ts = parse_timestamp(line)
            if ts:
                _last_ts = ts
                if ts >= cutoff:
                    _past_cutoff = True
            else:
                ts = _last_ts  # 继承上一行时间戳
            # 跳过cutoff之前的行; 一旦跨过cutoff, 后续无时间戳行也计入
            if not _past_cutoff and ts and ts < cutoff:
                continue

            # ── GCC任务匹配 ──
            for task_id, info in TASK_TAGS.items():
                for tag in info["tags"]:
                    if tag in line:
                        tasks[task_id]["count"] += 1
                        if len(tasks[task_id]["recent"]) < 5:
                            tasks[task_id]["recent"].append(line.strip()[:150])
                        if re.search(r"异常|ERROR|失败", line):
                            tasks[task_id]["errors"] += 1
                        break

            for pattern, key in METRIC_PATTERNS:
                m = re.search(pattern, line)
                if m and (not ts or ts >= cutoff):
                    metrics[key].append(m.groups())

            # ── VF过滤 ──
            m = RE_VF.search(line)
            if m:
                sym, plugin, _dir, _fval, _rvol = m.groups()
                vf_by_plugin[plugin][sym] += 1
                vf_by_symbol[sym] += 1
                vf_total += 1

            # ── L2 MACD ──
            m = RE_MACD_TRIGGER.search(line)
            if m:
                sym = m.group(1)
                macd_stats["trigger"] += 1
                macd_stats["by_symbol"][sym]["trigger"] += 1

            m = RE_MACD_REJECT.search(line)
            if m:
                macd_stats["reject"] += 1

            m = RE_MACD_FINAL.search(line)
            if m:
                sym, action, result = m.groups()
                if "成功" in result:
                    macd_stats["execute"] += 1
                    macd_stats["by_symbol"][sym]["execute"] += 1
                elif "拦截" in result:
                    macd_stats["gate_block"] += 1

            # ── KNN抑制 ──
            m = RE_KNN_SUPPRESS.search(line)
            if m:
                sym, plugin, _action = m.groups()
                knn_suppress[plugin][sym] += 1
                knn_suppress_total += 1

            # ── 外挂执行 ──
            m = RE_PLUGIN_EXEC.search(line)
            if m:
                result, _pe_action = m.group(1), m.group(3)
                if result == "成功":
                    plugin_exec["sent"] += 1
                    if _pe_action == "BUY":
                        plugin_exec["buy"] += 1
                    elif _pe_action == "SELL":
                        plugin_exec["sell"] += 1
                elif result == "冷却":
                    plugin_exec["skip"] += 1
                elif result in ("门控拦截", "失败"):
                    plugin_exec["block"] += 1

            # ── KEY-004治理 ──
            m = RE_GOVERNANCE.search(line)
            if m:
                governance_actions[m.group(4)] += 1

            # ── 扫描引擎外挂(scan engine) ──
            m = RE_SCAN_PLUGIN.search(line)
            if m:
                sym, plugin = m.group(1), m.group(2)
                # 中文名→英文名统一(dashboard显示用)
                _plugin_alias = {"缠论BS": "ChanBS", "飞云": "Feiyun", "剥头皮": "Chandelier"}
                plugin = _plugin_alias.get(plugin, plugin)
                scan_plugins[plugin]["scan"] += 1
                scan_plugins[plugin]["by_symbol"][sym]["scan"] += 1
                # 触发判断: 非触发/未激活/无触发=未触发, 其余=触发
                if "非触发" not in line and "未激活" not in line and "无触发" not in line:
                    scan_plugins[plugin]["trigger"] += 1
                    scan_plugins[plugin]["by_symbol"][sym]["trigger"] += 1

            # ── P0路径外挂触发(移动止损/止盈/VisionPattern/BrooksVision/N字结构) ──
            m = RE_P0_TRAILING.search(line)
            if m:
                plugin, sym = m.group(1), m.group(2)
                scan_plugins[plugin]["trigger"] += 1
                scan_plugins[plugin]["by_symbol"][sym]["trigger"] += 1

            m = RE_P0_VISION.search(line)
            if m:
                sym = m.group(1)
                scan_plugins["VisionPattern"]["trigger"] += 1
                scan_plugins["VisionPattern"]["by_symbol"][sym]["trigger"] += 1

            m = RE_P0_GCC47.search(line)
            if m:
                sym, plugin = m.group(1), m.group(2)
                scan_plugins[plugin]["trigger"] += 1
                scan_plugins[plugin]["by_symbol"][sym]["trigger"] += 1
                # BV信号用RE_BV_P0计数(server.log [P0收到]),这里不再重复累加

            m = RE_PLUGIN_EVENT.search(line)
            if m:
                phase, sym, source, action, executed, reason, _pe_price = m.groups()
                if phase == "dispatch":
                    scan_plugins[source]["dispatch"] += 1
                    # GCC-0197 S1: 记录dispatch事件供4H回填(price可选,后续response补)
                    if ts:
                        _pe_price_f = 0.0
                        if _pe_price:
                            try:
                                _pe_price_f = float(_pe_price)
                            except (ValueError, TypeError):
                                pass
                        plugin_signals.append({
                            "ts": ts.isoformat(), "symbol": sym,
                            "source": source, "action": action,
                            "price": _pe_price_f,
                        })
                elif phase == "response":
                    # GCC-0197 S1: response有price时回补dispatch缺失的price
                    if _pe_price and ts and plugin_signals:
                        try:
                            _resp_price = float(_pe_price)
                            if _resp_price > 0:
                                for _ps in reversed(plugin_signals):
                                    if _ps["symbol"] == sym and _ps["source"] == source and _ps["price"] == 0:
                                        _ps["price"] = _resp_price
                                        break
                        except (ValueError, TypeError):
                            pass
                    if executed.lower() == "true":
                        scan_plugins[source]["executed"] += 1
                        if source == "BrooksVision":
                            bv_stats["executed"] += 1
                    else:
                        scan_plugins[source]["blocked"] += 1
                        # 归类拦截原因
                        _br = (reason or "").strip()
                        if "门控拦截" in _br:
                            scan_plugins[source]["block_reasons"]["门控拦截"] += 1
                        elif "发送失败" in _br or "SignalStack" in _br or "3commas" in _br.lower() or "HTTP" in _br:
                            scan_plugins[source]["block_reasons"]["执行失败"] += 1
                        elif "FilterChain" in _br:
                            scan_plugins[source]["block_reasons"]["FilterChain"] += 1
                        elif "限次" in _br or "冷却" in _br or "去重" in _br:
                            scan_plugins[source]["block_reasons"]["限次/冷却"] += 1
                        elif "满仓" in _br or "仓位" in _br:
                            scan_plugins[source]["block_reasons"]["仓位限制"] += 1
                        elif "只做空" in _br or "只做多" in _br or "拒绝" in _br:
                            scan_plugins[source]["block_reasons"]["方向限制"] += 1
                        elif _br:
                            scan_plugins[source]["block_reasons"][_br[:20]] += 1
                        else:
                            scan_plugins[source]["block_reasons"]["未知"] += 1

            m = RE_BV_GATE.search(line)
            if m:
                bv_stats["gate_obs"] += 1

            # BV P0信号: [P0收到] SYMBOL BUY/SELL BrooksVision
            m = RE_BV_P0.search(line)
            if m:
                bv_stats["signals"] += 1

            # BV评估: 提取准确率+形态分布+BUY/SELL方向
            m = RE_BV_EVAL.search(line)
            if m:
                _bv_pattern, _bv_signal, _bv_result = m.group(2), m.group(3), m.group(4)
                bv_stats["eval"][_bv_result] += 1
                bv_stats["patterns"][_bv_pattern] += 1
                if _bv_signal in ("BUY", "SELL"):
                    bv_stats["by_direction"][_bv_signal] += 1

            # Vision方向过滤(L2主循环, 旧格式): [VISION_FILTER][拦截]
            m = RE_VISION_FILTER.search(line)
            if m:
                _vf_sym, _vf_action, _vf_reason = m.group(1), m.group(2), m.group(3)
                vision_filter["total"] += 1
                vision_filter["by_symbol"][_vf_sym] += 1
                if "anchor" in _vf_reason:
                    vision_filter["by_reason"]["anchor冲突"] += 1
                elif "完全相反" in _vf_reason:
                    vision_filter["by_reason"]["方向相反"] += 1
                else:
                    vision_filter["by_reason"]["其他"] += 1

            # GCC-0194新格式: [FILTER_CHAIN拦截] SYMBOL ACTION by REASON reason=TEXT
            m = RE_FILTER_CHAIN_BLOCK.search(line)
            if m:
                _fc_sym, _fc_action, _fc_by = m.group(1), m.group(2), m.group(3)
                _fc_reason_text = m.group(4).strip()
                vision_filter["total"] += 1
                vision_filter["by_symbol"][_fc_sym] += 1
                # 按blocked_by分类 (volume/vision/structure等)
                _fc_reason_key = _fc_by if _fc_by else (_fc_reason_text[:20] if _fc_reason_text else "其他")
                vision_filter["by_reason"][_fc_reason_key] += 1

            # ── deepseek_arbiter.log (JSON行) ──
            if "arbiter_decision" in line and line.strip().startswith("{"):
                try:
                    _arb = json.loads(line)
                    _arb_sig = _arb.get("arbiter_decision", {}).get("signal", "HOLD")
                    _arb_sym = _arb.get("symbol", "?")
                    arbiter["total"] += 1
                    arbiter["by_signal"][_arb_sig] += 1
                    arbiter["by_symbol"][_arb_sym][_arb_sig] += 1
                except (json.JSONDecodeError, KeyError):
                    pass

            # ── macd_divergence.log (文本块) ──
            m = RE_MACD_DIV_HEADER.search(line)
            if m:
                _macd_div_cur_sym = m.group(1)

            m = RE_MACD_DIV_MODE.search(line)
            if m:
                if m.group(1) == "SIGNAL_FOUND":
                    macd_div["found"] += 1
                elif m.group(1) == "FILTERED":
                    macd_div["filtered"] += 1

            m = RE_MACD_DIV_FILTER.search(line)
            if m:
                _mdf_reason = m.group(1).strip()
                # 归类: 去除具体数值,只保留类别
                if "背离强度不足" in _mdf_reason:
                    _mdf_reason = "背离强度不足"
                elif "顶分型拦截" in _mdf_reason:
                    _mdf_reason = "顶分型拦截BUY"
                elif "底分型拦截" in _mdf_reason:
                    _mdf_reason = "底分型拦截SELL"
                elif "支撑拦截" in _mdf_reason:
                    _mdf_reason = "支撑位拦截"
                elif "压力拦截" in _mdf_reason:
                    _mdf_reason = "压力位拦截"
                elif "低位拦截" in _mdf_reason:
                    _mdf_reason = "低位拦截"
                macd_div["filter_reasons"][_mdf_reason] += 1

            m = RE_MACD_DIV_STRENGTH.search(line)
            if m:
                macd_div["strengths"].append(float(m.group(1)))

            # ── rob_hoffman_plugin.log ──
            m = RE_RH_ER.search(line)
            if m:
                rh_stats["scans"] += 1
                _er_val = float(m.group(1))
                _er_thr = float(m.group(2))
                if _er_val < _er_thr:
                    rh_stats["er_below"] += 1

            m = RE_RH_FILTERED.search(line)
            if m:
                rh_stats["filtered"] += 1
                rh_stats["filter_reasons"][m.group(2).strip()] += 1

            m = RE_RH_SIGNAL.search(line)
            if m:
                rh_stats["signals"] += 1

            # ── l1_module_diagnosis.log ──
            m = RE_L1_DECISION.search(line)
            if m:
                _l1_sig = m.group(1)
                l1_stats["total"] += 1
                l1_stats["by_signal"][_l1_sig] += 1

            # ── value_analysis.log ──
            m = RE_VA_FALLBACK.search(line)
            if m:
                va_stats["fallback"] += 1
                _va_reason = m.group(2).strip()
                # 归类: HTTP xxx → HTTP错误
                if "HTTP Error" in _va_reason:
                    _code = re.search(r"HTTP Error (\d+)", _va_reason)
                    va_stats["fallback_reasons"][f"HTTP {_code.group(1)}" if _code else "HTTP其他"] += 1
                else:
                    va_stats["fallback_reasons"][_va_reason] += 1

            m = RE_VA_BATCH.search(line)
            if m:
                va_stats["batch_total"] += 1
                va_stats["batch_failed"] += int(m.group(2))

            # ── 门控拦截 ──
            _gate_checks = [
                (RE_GATE_K1, "KEY-001"),
                (RE_GATE_K2, "KEY-002"),
                (RE_GATE_ANTICHEAT, "ANTI-CHEAT"),
                (RE_GATE_ANCHOR, "ANCHOR"),
                (RE_GATE_MASTER, "MASTER-OBS"),
                (RE_GATE_VCACHE, "VCACHE"),
                (RE_GATE_VALUE, "VALUE-GUARD"),
                (RE_GATE_STALE, "DATA-STALE"),
            ]
            for rx, gname in _gate_checks:
                m = rx.search(line)
                if m:
                    sym = m.group(1)
                    gates[gname][sym] += 1
                    gate_totals[gname] += 1

            # N_GATE特殊处理(两种格式)
            m = RE_GATE_NGATE.search(line)
            if m:
                sym = m.group(1) or m.group(2)
                if sym:
                    gates["N_GATE"][sym] += 1
                    gate_totals["N_GATE"] += 1

            # 基准K线门控 + 唐纳奇周期 (GCC-0200)
            m = RE_BASELINE.search(line)
            if m:
                sym, direction, msg = m.group(1), m.group(2), m.group(3)
                baseline_stats["total"] += 1
                if "通过" in msg:
                    baseline_stats["pass"] += 1
                    baseline_stats["by_symbol"][sym]["pass"] += 1
                    baseline_stats["by_direction"][direction]["pass"] += 1
                elif "未找到" in msg:
                    baseline_stats["no_data"] += 1
                    baseline_stats["by_symbol"][sym]["no_data"] += 1
                    baseline_stats["by_direction"][direction]["no_data"] += 1
                else:
                    baseline_stats["block"] += 1
                    baseline_stats["by_symbol"][sym]["block"] += 1
                    baseline_stats["by_direction"][direction]["block"] += 1
                # DC周期统计
                if "[DC_BLOCK" in msg:
                    dc_stats["total"] += 1
                    dc_stats["block"] += 1
                elif "[DC_PASS" in msg:
                    dc_stats["total"] += 1
                    dc_stats["pass"] += 1
                elif "[DC_NODATA]" in msg:
                    dc_stats["total"] += 1
                    dc_stats["no_data"] += 1
          except OSError:
              continue  # 单行读取异常→跳过此行

    # ── SignalFilter 拦截数据 (GCC-0236 S15) ──
    try:
        _sf_path = Path(".GCC/signal_filter/filtered_signals.jsonl")
        if _sf_path.exists():
            gates["SignalFilter"] = defaultdict(int)
            for _sf_line in _sf_path.read_text(encoding="utf-8").strip().splitlines():
                try:
                    _sf = json.loads(_sf_line)
                    # 时间窗口过滤
                    _sf_ts_str = _sf.get("timestamp", "")
                    if _sf_ts_str:
                        _sf_ts = datetime.fromisoformat(_sf_ts_str).replace(tzinfo=None)
                        if _sf_ts < cutoff:
                            continue
                    # 只计入实际拦截或would_block
                    if not (_sf.get("blocked") or _sf.get("would_block")):
                        continue
                    _sf_source = _sf.get("source", "unknown")
                    gates["SignalFilter"][_sf_source] += 1
                    gate_totals["SignalFilter"] += 1
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass  # SF数据读取失败不影响主审计
    # ── 计算GCC任务状态 ──
    for task_id, t in tasks.items():
        if t["errors"] > 0:
            t["status"] = "ERROR"
        elif t["count"] == 0:
            t["status"] = "SILENT"
        elif t["count"] < t["expect"]:
            t["status"] = "LOW"
        else:
            t["status"] = "OK"

    # ── 汇总GCC指标 ──
    summary_metrics = {}
    if "vf_acc" in metrics:
        accs = [float(m[0]) for m in metrics["vf_acc"]]
        summary_metrics["vf_acc_avg"] = round(sum(accs) / len(accs), 4) if accs else 0
        summary_metrics["vf_acc_count"] = len(accs)
    if "macd_backfill" in metrics:
        summary_metrics["macd_backfilled"] = sum(int(m[0]) for m in metrics["macd_backfill"])
    if "knn_backfill" in metrics:
        summary_metrics["knn_backfilled"] = sum(int(m[0]) for m in metrics["knn_backfill"])
    if "card_distill" in metrics:
        last = metrics["card_distill"][-1]
        summary_metrics["card_total"] = int(last[0])
        summary_metrics["card_validated"] = int(last[1])
        summary_metrics["card_flagged"] = int(last[2])
    if "nc_result" in metrics:
        last = metrics["nc_result"][-1]
        summary_metrics["nc_scored"] = int(last[0])
        summary_metrics["nc_hit_rate"] = last[1]

    # ── 风险检测 + 改善建议 ──
    # category: execution(执行层) / data(数据层) / market(市场环境) / signal(信号质量) / system(系统)
    issues = []

    # GCC任务问题 → system
    for tid, t in tasks.items():
        if t["status"] == "SILENT" and t["expect"] > 0:
            issues.append({"task": tid, "type": "SILENT", "category": "system", "msg": f"{t['name']} 无日志输出"})
        elif t["status"] == "ERROR":
            issues.append({"task": tid, "type": "ERROR", "category": "system", "msg": f"{t['name']} 有{t['errors']}次异常"})
        elif t["status"] == "LOW":
            issues.append({"task": tid, "type": "LOW", "category": "system", "msg": f"{t['name']} 事件数({t['count']})低于预期({t['expect']})"})

    # 外挂风险: KNN抑制率过高 → signal
    if knn_suppress_total > 0 and vf_total > 0:
        suppress_rate = knn_suppress_total / max(vf_total, 1)
        if suppress_rate > 0.5:
            issues.append({"task": "PLUGIN", "type": "RISK", "category": "signal",
                           "msg": f"KNN抑制率过高({knn_suppress_total}/{vf_total}={suppress_rate:.0%}), 外挂信号可能被过度过滤"})

    # MACD风险: 触发多但执行少 → signal
    if macd_stats["trigger"] > 5 and macd_stats["execute"] == 0:
        issues.append({"task": "L2_MACD", "type": "RISK", "category": "signal",
                       "msg": f"MACD触发{macd_stats['trigger']}次但0执行, 门控可能过严"})
    if macd_stats["gate_block"] > macd_stats["execute"] and macd_stats["gate_block"] > 3:
        issues.append({"task": "L2_MACD", "type": "RISK", "category": "signal",
                       "msg": f"MACD被门控拦截{macd_stats['gate_block']}次>执行{macd_stats['execute']}次"})

    # BV风险: 准确率过低 → signal
    bv_decisive = bv_stats["eval"]["CORRECT"] + bv_stats["eval"]["INCORRECT"]
    if bv_decisive >= 5:
        bv_acc = bv_stats["eval"]["CORRECT"] / bv_decisive
        if bv_acc < 0.4:
            issues.append({"task": "BV", "type": "RISK", "category": "signal",
                           "msg": f"BrooksVision准确率{bv_acc:.0%}({bv_stats['eval']['CORRECT']}/{bv_decisive} decisive), 低于40%"})

    _is_weekend = _now_ny.weekday() >= 5
    stale_adjusted_by_symbol = {}
    stale_adjusted_total = 0
    for sym, cnt in gates.get("DATA-STALE", {}).items():
        # 周末美股休盘: 不计入DATA-STALE风险
        if _is_weekend and not _is_crypto_symbol_like(sym):
            continue
        stale_adjusted_by_symbol[sym] = cnt
        stale_adjusted_total += cnt

    # 门控风险: 某品种被大量拦截 → execution(SignalStack/3Commas相关) / data(DATA-STALE) / signal(其他门控)
    for gname, sym_counts in gates.items():
        _iter_items = stale_adjusted_by_symbol.items() if gname == "DATA-STALE" else sym_counts.items()
        for sym, cnt in _iter_items:
            if gname == "DATA-STALE":
                _th = 20 if _is_crypto_symbol_like(sym) else 40
            else:
                _th = 10
            if cnt < _th:
                continue
            if gname in ("SignalStack", "3Commas", "SS-FREEZE", "SS-COOLDOWN"):
                _gate_cat = "execution"
            elif gname == "DATA-STALE":
                _gate_cat = "data"
            else:
                _gate_cat = "signal"
            issues.append({"task": f"GATE-{gname}", "type": "RISK", "category": _gate_cat,
                           "msg": f"{sym} 被{gname}拦截{cnt}次, 检查是否合理"})

    # DATA-STALE风险 → data（周末美股休盘已过滤）
    stale_total = stale_adjusted_total
    gate_totals["DATA-STALE-ADJUSTED"] = stale_total
    if stale_total > 5:
        issues.append({"task": "DATA-STALE", "type": "RISK", "category": "data",
                       "msg": f"数据过期拦截{stale_total}次, 数据源可能不稳定"})

    # 仲裁器风险: HOLD率 > 90% → market
    if arbiter["total"] >= 10:
        _arb_hold = arbiter["by_signal"].get("HOLD", 0)
        _arb_hold_rate = _arb_hold / arbiter["total"]
        if _arb_hold_rate > 0.9:
            issues.append({"task": "ARBITER", "type": "RISK", "category": "market",
                           "msg": f"仲裁器HOLD率{_arb_hold_rate:.0%}({_arb_hold}/{arbiter['total']}), 过度保守"})

    # L1风险: HOLD率 > 95% → market
    if l1_stats["total"] >= 10:
        _l1_hold = l1_stats["by_signal"].get("HOLD", 0)
        _l1_hold_rate = _l1_hold / l1_stats["total"]
        if _l1_hold_rate > 0.95:
            issues.append({"task": "L1", "type": "RISK", "category": "market",
                           "msg": f"L1全品种HOLD率{_l1_hold_rate:.0%}({_l1_hold}/{l1_stats['total']}), 无有效信号"})

    # 估值风险: fallback率 → data
    if va_stats["fallback"] > 10:
        issues.append({"task": "VALUE", "type": "RISK", "category": "data",
                       "msg": f"估值FALLBACK {va_stats['fallback']}次, 数据源异常"})

    # RobHoffman风险: 震荡过滤率极高 → market
    if rh_stats["scans"] >= 10 and rh_stats["er_below"] > 0:
        _rh_tangled_rate = rh_stats["er_below"] / rh_stats["scans"]
        if _rh_tangled_rate > 0.9:
            issues.append({"task": "ROB_HOFFMAN", "type": "RISK", "category": "market",
                           "msg": f"RH震荡过滤率{_rh_tangled_rate:.0%}, ER低于阈值{rh_stats['er_below']}/{rh_stats['scans']}次"})

    # 外挂风险: 某外挂触发率极低 → market(0触发=市场无趋势) / execution(发送0执行)
    for pname, pdata in scan_plugins.items():
        # 仅当“扫描高 + 完全无触发/无派发/无执行”才告警，避免误报(已有dispatch/executed仍被判0触发)
        if pdata["scan"] > 50 and pdata["trigger"] == 0 and pdata["dispatch"] == 0 and pdata["executed"] == 0:
            issues.append({"task": f"PLUGIN-{pname}", "type": "RISK", "category": "market",
                           "msg": f"{pname} 扫描{pdata['scan']}次但0触发, 可能阈值过高"})
        if pdata["dispatch"] > 5 and pdata["executed"] == 0:
            issues.append({"task": f"PLUGIN-{pname}", "type": "RISK", "category": "execution",
                           "msg": f"{pname} 发送{pdata['dispatch']}次但0执行, 全被门控拦截"})

    # ── 日志覆盖率检查: 只在每天8am slot执行(check_coverage=True) ──
    if check_coverage:
        EXPECTED_CRYPTO = {"BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"}
        EXPECTED_STOCKS = {"TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR"}
        EXPECTED_ALL = EXPECTED_CRYPTO | EXPECTED_STOCKS
        # 从VF/gates/knn中提取实际出现的品种
        _seen_symbols = set()
        _seen_symbols.update(vf_by_symbol.keys())
        for _gs in gates.values():
            _seen_symbols.update(_gs.keys())
        # macd_stats["by_symbol"]的key就是品种名
        _seen_symbols.update(macd_stats.get("by_symbol", {}).keys())
        for _pn, _psyms in vf_by_plugin.items():
            _seen_symbols.update(_psyms.keys())
        for _kn, _ksyms in knn_suppress.items():
            _seen_symbols.update(_ksyms.keys())
        # 映射内部名→标准名(BTCUSDC→BTC-USD)
        _sym_map = {"BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD", "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD"}
        _normalized = {_sym_map.get(s, s) for s in _seen_symbols}

        _missing = EXPECTED_ALL - _normalized
        if _missing:
            _missing_crypto = _missing & EXPECTED_CRYPTO
            _missing_stocks = _missing & EXPECTED_STOCKS
            _weekday = datetime.now(NY_TZ).weekday()  # 0=Mon..6=Sun
            _is_weekend = _weekday >= 5
            if _missing_crypto:
                issues.append({"task": "COVERAGE", "type": "ERROR", "category": "system",
                               "msg": f"加密品种日志缺失: {', '.join(sorted(_missing_crypto))} — 模块可能未运行"})
            if _missing_stocks and not _is_weekend:
                issues.append({"task": "COVERAGE", "type": "ERROR", "category": "system",
                               "msg": f"股票品种日志缺失(工作日): {', '.join(sorted(_missing_stocks))} — 模块可能未运行"})
            elif _missing_stocks and _is_weekend:
                issues.append({"task": "COVERAGE", "type": "LOW", "category": "system",
                               "msg": f"股票品种周末无日志(正常): {', '.join(sorted(_missing_stocks))}"})

    # ── KEY-009 Phase2: 交易生命周期分析 ──
    trade_analysis = _analyze_completed_trades(hours)

    # ── KEY-009 Phase2: FIFO配对 + 拦截验证 + 策略排行 ──
    fifo_trades = _fifo_pair_trades(hours)
    block_validation = _validate_blocks(hours)
    strategy_ranking = _rank_strategies(fifo_trades, block_validation)

    # 交易相关风险检测 → signal
    ta = trade_analysis
    if ta["total"] >= 10 and ta["win_rate"] < 0.35:
        issues.append({"task": "TRADE", "type": "RISK", "category": "signal",
                       "msg": f"整体胜率过低: {ta['win_rate']:.1%} ({ta['winners']}/{ta['total']})"})
    for pname, pstat in ta.get("by_plugin", {}).items():
        if pstat["total"] >= 5 and pstat["win_rate"] < 0.25:
            issues.append({"task": "TRADE", "type": "RISK", "category": "signal",
                           "msg": f"插件 {pname} 胜率异常: {pstat['win_rate']:.1%} ({pstat['winners']}/{pstat['total']})"})
    # 样本过少时平均持仓时长波动大，提升到10笔再告警
    if ta["avg_hold_min"] > 480 and ta["total"] >= 10:
        issues.append({"task": "TRADE", "type": "RISK", "category": "signal",
                       "msg": f"平均持仓过长: {ta['avg_hold_min']:.0f}分钟 ({ta['avg_hold_min']/60:.1f}小时)"})

    # ── GCC-0197 S2: 外挂信号准确率回填 ──
    plugin_accuracy = _plugin_accuracy_backfill(plugin_signals)

    # ── GCC-0172: BV信号准确率 (从独立state文件读取) ──
    bv_accuracy = {}
    bv_acc_path = STATE_DIR / "bv_signal_accuracy.json"
    if bv_acc_path.exists():
        try:
            bv_accuracy = json.loads(bv_acc_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # GCC-0172: 按形态准确率检测低质量形态
    # GCC-0243: 已在黑名单的形态不再报RISK (避免历史数据干扰)
    _bv_blacklist = {"BEAR_FLAG"}  # 同步 brooks_vision.py / filter_chain_worker.py
    for pat_name, pat_data in bv_accuracy.get("patterns", {}).items():
        if pat_name in _bv_blacklist:
            continue
        dec = pat_data.get("decisive", 0)
        acc = pat_data.get("accuracy", 0)
        if dec >= 10 and acc < 0.4:
            issues.append({"task": "BV-PATTERN", "type": "RISK", "category": "signal",
                           "msg": f"BV形态 {pat_name} 准确率{acc:.0%}({dec}笔decisive), 建议降级或排除"})

    # ── 系统亮点 (POSITIVE) — 与问题并列输出 ──
    # FIFO交易: 整体胜率高
    ft = fifo_trades
    if ft["total"] >= 5 and ft.get("win_rate", 0) >= 0.45:
        issues.append({"task": "TRADE", "type": "POSITIVE", "category": "signal",
                       "msg": f"整体胜率{ft['win_rate']:.0%}({ft.get('winners',0)}/{ft['total']}), 策略整体有效"})
    # FIFO: 最赚钱的品种
    best_sym = max(ft.get("by_symbol", {}).items(), key=lambda x: x[1].get("total_pnl", 0), default=(None, {}))
    if best_sym[0] and best_sym[1].get("total_pnl", 0) > 0:
        issues.append({"task": "TRADE", "type": "POSITIVE", "category": "signal",
                       "msg": f"最佳品种 {best_sym[0]}: 总PnL +{best_sym[1]['total_pnl']:.1f}% ({best_sym[1].get('trades',0)}笔)"})
    # FIFO: 最赚钱的外挂
    best_src = max(ft.get("by_source", {}).items(), key=lambda x: x[1].get("total_pnl", 0), default=(None, {}))
    if best_src[0] and best_src[1].get("total_pnl", 0) > 0:
        issues.append({"task": "TRADE", "type": "POSITIVE", "category": "signal",
                       "msg": f"最佳外挂 {best_src[0]}: 总PnL +{best_src[1]['total_pnl']:.1f}% (胜率{best_src[1].get('win_rate',0):.0%})"})
    # BV准确率
    bv_overall = bv_accuracy.get("overall", {})
    if bv_overall.get("decisive", 0) >= 5 and bv_overall.get("accuracy", 0) >= 0.55:
        issues.append({"task": "BV", "type": "POSITIVE", "category": "signal",
                       "msg": f"BrooksVision准确率{bv_overall['accuracy']:.0%}({bv_overall['decisive']}笔decisive), 形态识别可靠"})
    # BV: 最佳形态
    best_pat = max(bv_accuracy.get("patterns", {}).items(),
                   key=lambda x: x[1].get("accuracy", 0) if x[1].get("decisive", 0) >= 3 else 0, default=(None, {}))
    if best_pat[0] and best_pat[1].get("decisive", 0) >= 3 and best_pat[1].get("accuracy", 0) >= 0.6:
        issues.append({"task": "BV-PATTERN", "type": "POSITIVE", "category": "signal",
                       "msg": f"最佳形态 {best_pat[0]}: 准确率{best_pat[1]['accuracy']:.0%}({best_pat[1]['decisive']}笔)"})
    # 拦截验证: 正确率高
    bv_val = block_validation
    if bv_val.get("validated", 0) >= 5 and bv_val.get("accuracy", 0) >= 0.6:
        issues.append({"task": "BLOCK", "type": "POSITIVE", "category": "signal",
                       "msg": f"信号拦截正确率{bv_val['accuracy']:.0%}({bv_val['correct']}/{bv_val['validated']}), 过滤逻辑有效"})
    # 拦截验证: 最有效的过滤原因
    best_reason = max(bv_val.get("by_reason", {}).items(),
                      key=lambda x: x[1].get("accuracy", 0) if x[1].get("total", 0) >= 3 else 0, default=(None, {}))
    if best_reason[0] and best_reason[1].get("total", 0) >= 3 and best_reason[1].get("accuracy", 0) >= 0.6:
        issues.append({"task": "BLOCK", "type": "POSITIVE", "category": "signal",
                       "msg": f"最有效过滤: {best_reason[0]} 正确率{best_reason[1]['accuracy']:.0%}({best_reason[1]['total']}次)"})
    # MACD: 执行率高
    if macd_stats["trigger"] >= 3 and macd_stats["execute"] > 0:
        macd_exec_rate = macd_stats["execute"] / max(macd_stats["trigger"], 1)
        if macd_exec_rate >= 0.3:
            issues.append({"task": "L2_MACD", "type": "POSITIVE", "category": "signal",
                           "msg": f"MACD背离执行率{macd_exec_rate:.0%}({macd_stats['execute']}/{macd_stats['trigger']}), 信号质量稳定"})
    # GCC任务: 全部正常
    ok_tasks = sum(1 for t in tasks.values() if t["status"] == "OK")
    total_tasks = len(tasks)
    if total_tasks > 0 and ok_tasks / total_tasks >= 0.8:
        issues.append({"task": "SYSTEM", "type": "POSITIVE", "category": "system",
                       "msg": f"GCC任务健康度{ok_tasks}/{total_tasks}({ok_tasks/total_tasks:.0%}), 系统运行稳定"})

    # ── KEY-009 全链路交叉分析 ──
    pipeline_analysis = _build_pipeline_analysis(dict(scan_plugins), trade_analysis, plugin_accuracy)

    # ── GCC-0197 S3: 外挂Phase升降级 ──
    plugin_phases = _plugin_phase_update(plugin_accuracy)

    # ── GCC-0252 A4: 方向锁 leader 每周更新 ──
    try:
        from gcc_trading_module import compute_direction_leaders
        _dir_leaders = compute_direction_leaders()
        logger.info("[KEY-009] direction leaders updated: %d symbols", len(_dir_leaders))
    except Exception as _e:
        logger.warning("[KEY-009] direction leaders update failed: %s", _e)

    # ── KEY-009 券商对账 ──
    broker_match = _match_broker_trades(hours)

    # ── GCC-0202: 五层进化系统评分 ──
    system_evo = _build_system_evo(
        trade_analysis, tasks, issues,
        dict(scan_plugins), dict(plugin_exec), hours,
        gates, dict(gate_totals))

    # ── 基准K线状态 ──
    _bl_state = {}
    try:
        _bl_path = Path(__file__).parent / "state" / "baseline_state.json"
        if _bl_path.exists():
            _bl_state = json.loads(_bl_path.read_text())
    except Exception:
        pass
    _baseline_data = {
        "stats": {
            "total": baseline_stats["total"],
            "pass": baseline_stats["pass"],
            "block": baseline_stats["block"],
            "no_data": baseline_stats["no_data"],
            "by_symbol": {s: dict(d) for s, d in baseline_stats["by_symbol"].items()},
            "by_direction": {d: dict(v) for d, v in baseline_stats["by_direction"].items()},
        },
        "dc_stats": dict(dc_stats),
        "state": _bl_state,
    }

    return _build_result(now_str, hours, tasks, summary_metrics,
                         dict(vf_by_plugin), macd_stats, dict(knn_suppress),
                         knn_suppress_total, plugin_exec, dict(governance_actions),
                         bv_stats, gates, dict(gate_totals), issues,
                         vf_by_symbol=dict(vf_by_symbol), vf_total=vf_total,
                         scan_plugins=dict(scan_plugins),
                         vision_filter=vision_filter,
                         arbiter=arbiter, macd_div=macd_div,
                         rh_stats=rh_stats, l1_stats=l1_stats,
                         va_stats=va_stats,
                         trade_analysis=trade_analysis,
                         pipeline_analysis=pipeline_analysis,
                         bv_accuracy=bv_accuracy,
                         fifo_trades=fifo_trades,
                         block_validation=block_validation,
                         strategy_ranking=strategy_ranking,
                         broker_match=broker_match,
                         plugin_accuracy=plugin_accuracy,
                         plugin_phases=plugin_phases,
                         baseline_data=_baseline_data,
                         system_evo=system_evo)


def _load_system_config() -> dict:
    """读取系统可调参数的当前值，供诊断引用。"""
    cfg = {"daily_bias": {}, "n_min_quality": 0.65, "fc_weight_thresholds": {}}

    # daily_bias.json
    bias_path = ROOT / "daily_bias.json"
    try:
        if bias_path.exists():
            bd = json.loads(bias_path.read_text(encoding="utf-8"))
            cfg["daily_bias"] = bd.get("bias", {})
            cfg["daily_bias_date"] = bd.get("date", "")
    except Exception:
        pass

    # n_structure.py → _min_quality
    ns_path = ROOT / "n_structure.py"
    try:
        if ns_path.exists():
            for line in ns_path.read_text(encoding="utf-8").splitlines():
                m = re.search(r"_min_quality\s*=\s*([0-9.]+)", line)
                if m:
                    cfg["n_min_quality"] = float(m.group(1))
                    break
    except Exception:
        pass

    # filter_chain_worker.py → weight thresholds
    fc_path = ROOT / "filter_chain_worker.py"
    try:
        if fc_path.exists():
            _fc_text = fc_path.read_text(encoding="utf-8")
            for pat, key in [
                (r'weight\s*>=\s*([0-9.]+).*?"FULL"', "full"),
                (r'weight\s*>=\s*([0-9.]+).*?"STANDARD"', "standard"),
                (r'weight\s*>=\s*([0-9.]+).*?"REDUCED"', "reduced"),
            ]:
                m = re.search(pat, _fc_text)
                if m:
                    cfg["fc_weight_thresholds"][key] = float(m.group(1))
    except Exception:
        pass

    # price_scan_engine → MAX_UNITS_PER_SYMBOL
    pse_path = ROOT / "price_scan_engine_v21.py"
    try:
        if pse_path.exists():
            for line in pse_path.read_text(encoding="utf-8").splitlines()[:1200]:
                m = re.search(r"MAX_UNITS_PER_SYMBOL\s*=\s*(\d+)", line)
                if m:
                    cfg["max_units"] = int(m.group(1))
                m = re.search(r"TRAILING_STOP_ENABLED\s*=\s*(True|False)", line)
                if m:
                    cfg["trailing_stop"] = m.group(1) == "True"
    except Exception:
        pass

    return cfg


def _build_pipeline_analysis(scan_plugins: dict, trade_analysis: dict,
                             plugin_accuracy: dict = None) -> list:
    """全链路信号→盈亏交叉分析: 每个外挂的信号质量+具体参数诊断。
    交叉关联 scan_plugins (漏斗) + trade_analysis.by_plugin (盈亏) + plugin_accuracy (4H回填)。
    读取实际系统配置，建议引用具体参数名和当前值。"""
    cfg = _load_system_config()
    plugin_accuracy = plugin_accuracy or {}
    bias = cfg.get("daily_bias", {})
    bias_date = cfg.get("daily_bias_date", "")
    n_min_q = cfg.get("n_min_quality", 0.65)

    pipelines = []
    by_plugin = trade_analysis.get("by_plugin", {})
    all_plugins = set(scan_plugins.keys()) | set(by_plugin.keys())

    # 外挂→配置文件映射 (用于具体建议)
    PLUGIN_CONFIG = {
        "ChanBS":        {
            "file": "chan_bs_plugin.py",
            "params": "min_strength（process_for_scan默认0.15；symbol默认: crypto=0.25 / stock=0.35）",
        },
        "SuperTrend":    {
            "file": "supertrend_av2_plugin.py",
            "params": "atr_period=9 / atr_multiplier=3.9",
            "trigger_hint": "当前 price_scan_engine_v21.py 中 _scan_supertrend_av2() 调用仍被注释，且 crypto/stock 的 supertrend_av2.enabled 都是 False；先恢复扫描入口并启用配置，再评估 atr_period=9 / atr_multiplier=3.9",
        },
        "RobHoffman":    {
            "file": "rob_hoffman_plugin.py",
            "params": "KAMA_ER_TANGLED_THRESHOLD=0.18 / KAMA_ER_PERIOD=10 / IRB_WICK_PCT=0.34",
            "trigger_hint": "当前参数已比旧建议更宽松，且 crypto.rob_hoffman.enabled=True / stock.rob_hoffman.enabled=False；若扫描仍0触发，应优先复查未激活原因而不是继续沿用旧参数建议",
        },
        "BrooksVision":  {"file": "brooks_vision.py", "params": "confidence阈值/形态过滤"},
        "Chandelier":    {"file": "chandelier_zlsma_plugin.py", "params": "atr_period/atr_mult"},
        "Feiyun":        {"file": "feiyun_plugin.py", "params": "ma_period/threshold"},
        "VisionPattern": {"file": "price_scan_engine_v21.py", "params": "VISION_PATTERN_OBSERVE_*"},
        "移动止盈":       {"file": "price_scan_engine_v21.py", "params": "TRAILING_STOP_ENABLED/回撤比例"},
        "移动止损":       {"file": "price_scan_engine_v21.py", "params": "TRAILING_STOP_ENABLED/止损比例"},
        "N字结构":        {"file": "n_structure.py", "params": f"_min_quality(当前={n_min_q})"},
    }

    for pname in sorted(all_plugins):
        sp = scan_plugins.get(pname, {})
        tp = by_plugin.get(pname, {})

        scan = sp.get("scan", 0)
        trigger = sp.get("trigger", 0)
        dispatch = sp.get("dispatch", 0)
        executed = sp.get("executed", 0)
        blocked = sp.get("blocked", 0)
        block_reasons = dict(sp.get("block_reasons", {})) if isinstance(sp.get("block_reasons"), dict) else {}

        trades_total = tp.get("total", 0)
        trades_won = tp.get("winners", 0)
        win_rate = tp.get("win_rate", 0.0)

        # GCC-0197 信号准确率 (4H回填)
        pa_src = plugin_accuracy.get(pname, {})
        pa_overall = pa_src.get("_overall", {})
        signal_acc = pa_overall.get("acc")  # None if no data
        signal_acc_total = pa_overall.get("total", 0)

        trigger_rate = round(trigger / max(scan, 1), 3) if scan > 0 else None
        exec_rate = round(executed / max(dispatch, 1), 3) if dispatch > 0 else None
        block_rate = round(blocked / max(dispatch, 1), 3) if dispatch > 0 else None

        # ── 信号质量评分 (0-100) ──
        score_parts = []
        if trigger_rate is not None and scan >= 10:
            tr_score = min(trigger_rate / 0.3, 1.0) * 100 if trigger_rate <= 0.3 else max(0, (0.6 - trigger_rate) / 0.3 * 100)
            score_parts.append(("trigger", tr_score, 0.2))
        if exec_rate is not None and dispatch >= 3:
            score_parts.append(("exec", exec_rate * 100, 0.3))
        if trades_total >= 3:
            score_parts.append(("win", win_rate * 100, 0.4))
        if signal_acc is not None and signal_acc_total >= 5:
            score_parts.append(("signal_acc", signal_acc * 100, 0.3))

        if score_parts:
            total_weight = sum(w for _, _, w in score_parts)
            quality_score = round(sum(s * w for _, s, w in score_parts) / total_weight, 1)
        else:
            quality_score = None

        # ── 诊断 + 处方 ──
        pcfg = PLUGIN_CONFIG.get(pname, {"file": "unknown", "params": ""})
        recommendations = []

        # --- 诊断1: 触发率 ---
        if scan >= 20 and trigger == 0:
            trigger_hint = pcfg.get("trigger_hint")
            action = (f"扫描{scan}次0触发 → {trigger_hint}"
                      if trigger_hint else
                      f"扫描{scan}次0触发 → 修改 {pcfg['file']} 中 {pcfg['params']}，降低触发阈值")
            recommendations.append({
                "target": "外挂参数",
                "action": action,
                "priority": "HIGH"
            })
        elif trigger_rate is not None and trigger_rate > 0.5 and scan >= 20:
            recommendations.append({
                "target": "外挂参数",
                "action": f"触发率{trigger_rate:.0%}过高(理想10-30%) → {pcfg['file']} 提高 {pcfg['params']}",
                "priority": "MEDIUM"
            })

        # --- 诊断2: 执行率 (按拦截原因细分处方) ---
        if dispatch >= 3 and blocked > 0:
            gate_cnt = block_reasons.get("门控拦截", 0)
            exec_fail = block_reasons.get("执行失败", 0)
            dir_cnt = block_reasons.get("方向限制", 0)
            pos_cnt = block_reasons.get("仓位限制", 0)
            cool_cnt = block_reasons.get("限次/冷却", 0)

            if gate_cnt > 0 and gate_cnt >= blocked * 0.4:
                recommendations.append({
                    "target": "过滤参数",
                    "action": f"门控拦截{gate_cnt}次({gate_cnt}/{dispatch}={gate_cnt/dispatch:.0%}) → "
                              f"n_structure.py _min_quality(当前{n_min_q}) 降至0.55可放行更多; "
                              f"或 llm_server KEY001_VCACHE_MODE 从observe改soft",
                    "priority": "HIGH" if executed == 0 else "MEDIUM"
                })

            if exec_fail > 0 and exec_fail >= blocked * 0.3:
                recommendations.append({
                    "target": "执行层",
                    "action": f"发送失败{exec_fail}次 → 检查SignalStack连接(Schwab 7天过期), "
                              f"SS_FREEZE_SECONDS=1800(30min冻结)",
                    "priority": "HIGH"
                })

            if dir_cnt > 0 and dir_cnt >= blocked * 0.2:
                # 找出哪些品种被方向限制
                by_sym = sp.get("by_symbol", {})
                bias_conflicts = []
                for sym in by_sym:
                    sym_bias = bias.get(sym, "SIDE")
                    if sym_bias != "SIDE":
                        bias_conflicts.append(f"{sym}={sym_bias}")
                bias_str = ", ".join(bias_conflicts[:5]) if bias_conflicts else "检查daily_bias.json"
                recommendations.append({
                    "target": "过滤逻辑",
                    "action": f"方向限制{dir_cnt}次 → daily_bias.json(日期{bias_date}): {bias_str}; "
                              f"如市场反转需更新set_bias.py",
                    "priority": "MEDIUM"
                })

            if pos_cnt > 0 and pos_cnt >= blocked * 0.2:
                max_units = cfg.get("max_units", 5)
                recommendations.append({
                    "target": "过滤参数",
                    "action": f"仓位限制{pos_cnt}次 → MAX_UNITS_PER_SYMBOL={max_units}(scan_engine), "
                              f"已满仓品种需先减仓才能开新",
                    "priority": "LOW"
                })

            if cool_cnt > 0:
                recommendations.append({
                    "target": "正常防护",
                    "action": f"限次/冷却{cool_cnt}次 → P0每品种日限3次, 正常风控无需调整",
                    "priority": "LOW"
                })

        elif dispatch >= 5 and blocked == 0 and executed == 0:
            recommendations.append({
                "target": "执行层",
                "action": f"dispatch {dispatch}次但0执行0拦截 — 信号可能在发送环节丢失, 检查server.log P0路径",
                "priority": "HIGH"
            })

        # --- 诊断3: 胜率 (结合具体外挂给针对性建议) ---
        if trades_total >= 5:
            if win_rate < 0.25:
                recommendations.append({
                    "target": "外挂本身",
                    "action": f"胜率{win_rate:.0%}({trades_won}/{trades_total}) → "
                              f"暂停{pname}或重写核心逻辑({pcfg['file']}); "
                              f"当前{pname}产出的信号多数亏损",
                    "priority": "HIGH"
                })
            elif win_rate < 0.4:
                recommendations.append({
                    "target": "外挂参数",
                    "action": f"胜率{win_rate:.0%}偏低 → {pcfg['file']} 收紧 {pcfg['params']} 减少低质量信号; "
                              f"或增加FilterChain volume_score要求(当前>=0.7加成)",
                    "priority": "MEDIUM"
                })
        elif 0 < trades_total < 5:
            recommendations.append({
                "target": "观察",
                "action": f"样本{trades_total}笔不足(需≥5) → 继续积累",
                "priority": "LOW"
            })

        # --- 诊断4: 信号准确率 (GCC-0197 4H回填) ---
        if signal_acc is not None and signal_acc_total >= 5:
            if signal_acc < 0.35:
                recommendations.append({
                    "target": "外挂本身",
                    "action": f"信号准确率{signal_acc:.0%}({signal_acc_total}笔4H回填) → "
                              f"{pcfg['file']} 核心逻辑产生的信号方向多数错误",
                    "priority": "HIGH"
                })
            elif signal_acc >= 0.6:
                recommendations.append({
                    "target": "强化优点",
                    "action": f"信号准确率{signal_acc:.0%}({signal_acc_total}笔) → "
                              f"信号方向判断准确, 考虑放宽执行限制增加交易量",
                    "priority": "POSITIVE"
                })

        # --- 诊断5: 优点强化 ---
        if trades_total >= 5 and win_rate >= 0.5:
            boost_advice = []
            if gate_cnt := block_reasons.get("门控拦截", 0):
                boost_advice.append(f"放宽门控(当前拦截{gate_cnt}次)可增加交易量")
            if dir_cnt := block_reasons.get("方向限制", 0):
                boost_advice.append(f"放宽方向限制({dir_cnt}次)让{pname}双向交易")
            if not boost_advice:
                boost_advice.append("维持当前配置, 监控胜率变化")
            recommendations.append({
                "target": "强化优点",
                "action": f"胜率{win_rate:.0%}优秀 → " + "; ".join(boost_advice),
                "priority": "POSITIVE"
            })
        elif trades_total >= 3 and win_rate >= 0.6:
            recommendations.append({
                "target": "强化优点",
                "action": f"胜率{win_rate:.0%}(样本{trades_total}) → 继续观察, 若稳定>=5笔后可放量",
                "priority": "POSITIVE"
            })

        # --- 诊断5: 漏斗断裂 ---
        if trigger > 5 and dispatch == 0 and trades_total == 0:
            recommendations.append({
                "target": "过滤逻辑",
                "action": f"触发{trigger}次但0次dispatch → FilterChain全部拦截, "
                          f"检查filter_chain_worker.py weight计算(SKIP阈值<0.5)",
                "priority": "HIGH"
            })

        pipelines.append({
            "plugin": pname,
            "funnel": {"scan": scan, "trigger": trigger, "dispatch": dispatch,
                       "executed": executed, "blocked": blocked},
            "rates": {"trigger_rate": trigger_rate, "exec_rate": exec_rate, "block_rate": block_rate},
            "trades": {"total": trades_total, "winners": trades_won, "win_rate": win_rate},
            "signal_accuracy": {"acc": signal_acc, "total": signal_acc_total,
                                "by_symbol": {s: d for s, d in pa_src.items() if s != "_overall"}},
            "block_reasons": block_reasons,
            "quality_score": quality_score,
            "recommendations": recommendations,
        })

    pipelines.sort(key=lambda x: (x["quality_score"] is None, x["quality_score"] or 999))
    return pipelines


def _analyze_completed_trades(hours: int) -> dict:
    """读取 plugin_profit_state.json 的 completed_trades，按时间窗口分析胜率/亏损。"""
    result = {
        "total": 0, "winners": 0, "losers": 0, "win_rate": 0.0,
        "avg_pnl_pct": 0.0, "avg_winner_pct": 0.0, "avg_loser_pct": 0.0,
        "total_pnl": 0.0,
        "by_symbol": {}, "by_plugin": {},
        "avg_hold_min": 0.0, "longest_loser_min": 0.0,
    }
    state_path = ROOT / "state" / "plugin_profit_state.json"
    if not state_path.exists():
        return result
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return result

    completed = data.get("completed_trades", [])
    if not completed:
        return result

    cutoff = datetime.now(NY_TZ) - timedelta(hours=hours)
    trades = []
    for t in completed:
        sell_ts = t.get("sell_ts", "")
        if not sell_ts:
            continue
        try:
            ts = datetime.fromisoformat(sell_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=NY_TZ)
            if ts < cutoff:
                continue
        except Exception:
            continue
        trades.append(t)

    if not trades:
        return result

    winners = [t for t in trades if t.get("pnl", 0) > 0]
    losers = [t for t in trades if t.get("pnl", 0) <= 0]
    all_pnl_pct = [t.get("pnl_pct", 0) for t in trades]
    winner_pcts = [t.get("pnl_pct", 0) for t in winners]
    loser_pcts = [t.get("pnl_pct", 0) for t in losers]

    # 持仓时长
    hold_mins = []
    for t in trades:
        try:
            buy_ts = datetime.fromisoformat(t["buy_ts"])
            sell_ts = datetime.fromisoformat(t["sell_ts"])
            hold_mins.append((sell_ts - buy_ts).total_seconds() / 60)
        except Exception:
            pass
    loser_hold_mins = []
    for t in losers:
        try:
            buy_ts = datetime.fromisoformat(t["buy_ts"])
            sell_ts = datetime.fromisoformat(t["sell_ts"])
            loser_hold_mins.append((sell_ts - buy_ts).total_seconds() / 60)
        except Exception:
            pass

    # 按品种统计
    by_symbol = defaultdict(lambda: {"total": 0, "winners": 0, "total_pnl": 0.0})
    for t in trades:
        s = t.get("symbol", "UNKNOWN")
        by_symbol[s]["total"] += 1
        if t.get("pnl", 0) > 0:
            by_symbol[s]["winners"] += 1
        by_symbol[s]["total_pnl"] += t.get("pnl", 0)

    # 按插件统计 (buy_plugin)
    by_plugin = defaultdict(lambda: {"total": 0, "winners": 0})
    for t in trades:
        p = t.get("buy_plugin", "Unknown")
        by_plugin[p]["total"] += 1
        if t.get("pnl", 0) > 0:
            by_plugin[p]["winners"] += 1

    n = len(trades)
    result["total"] = n
    result["winners"] = len(winners)
    result["losers"] = len(losers)
    result["win_rate"] = round(len(winners) / n, 3)
    result["avg_pnl_pct"] = round(sum(all_pnl_pct) / n, 2)
    result["avg_winner_pct"] = round(sum(winner_pcts) / max(len(winner_pcts), 1), 2)
    result["avg_loser_pct"] = round(sum(loser_pcts) / max(len(loser_pcts), 1), 2)
    result["total_pnl"] = round(sum(t.get("pnl", 0) for t in trades), 2)
    result["avg_hold_min"] = round(sum(hold_mins) / max(len(hold_mins), 1), 1)
    result["longest_loser_min"] = round(max(loser_hold_mins) if loser_hold_mins else 0, 1)
    result["by_symbol"] = {s: {"total": d["total"], "winners": d["winners"],
                                "win_rate": round(d["winners"] / max(d["total"], 1), 3),
                                "total_pnl": round(d["total_pnl"], 2)}
                           for s, d in by_symbol.items()}
    result["by_plugin"] = {p: {"total": d["total"], "winners": d["winners"],
                                "win_rate": round(d["winners"] / max(d["total"], 1), 3)}
                           for p, d in by_plugin.items()}
    return result


# ============================================================
# KEY-009 Phase2: FIFO交易配对 (trade_history.json)
# ============================================================

def _fifo_pair_trades(hours: int) -> dict:
    """从trade_history.json FIFO配对BUY→SELL，按外挂×品种统计盈亏。
    只处理有source字段的记录(2/8之后)。"""
    result = {
        "total": 0, "winners": 0, "win_rate": 0.0, "avg_pnl_pct": 0.0,
        "total_pnl_pct": 0.0,
        "by_source": {}, "by_symbol": {}, "by_source_symbol": {},
    }
    th_path = ROOT / "logs" / "trade_history.json"
    if not th_path.exists():
        return result
    try:
        records = json.loads(th_path.read_text(encoding="utf-8"))
    except Exception:
        return result

    cutoff = datetime.now(NY_TZ) - timedelta(hours=hours)

    # 按symbol分组, FIFO配对
    from collections import deque
    buy_queues = defaultdict(deque)  # symbol → deque of {ts, price, source}
    pairs = []

    for r in sorted(records, key=lambda x: x.get("ts", "")):
        if not r.get("source") or not r.get("price"):
            continue
        try:
            ts = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
            ts = ts.replace(tzinfo=NY_TZ)
        except Exception:
            continue

        sym = r["symbol"]
        action = r.get("action", "")

        if action == "BUY":
            buy_queues[sym].append({"ts": ts, "price": r["price"], "source": r["source"]})
        elif action == "SELL" and buy_queues[sym]:
            buy = buy_queues[sym].popleft()
            # 只计入sell时间在cutoff之后的配对
            if ts >= cutoff:
                pnl_pct = (r["price"] - buy["price"]) / buy["price"] * 100
                pairs.append({
                    "symbol": sym,
                    "source": buy["source"],
                    "buy_price": buy["price"],
                    "sell_price": r["price"],
                    "pnl_pct": pnl_pct,
                })

    if not pairs:
        return result

    # 统计
    winners = [p for p in pairs if p["pnl_pct"] > 0]
    result["total"] = len(pairs)
    result["winners"] = len(winners)
    result["win_rate"] = round(len(winners) / len(pairs), 3)
    result["avg_pnl_pct"] = round(sum(p["pnl_pct"] for p in pairs) / len(pairs), 2)
    result["total_pnl_pct"] = round(sum(p["pnl_pct"] for p in pairs), 2)

    # by_source
    src_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_sum": 0.0})
    for p in pairs:
        s = src_stats[p["source"]]
        s["trades"] += 1
        if p["pnl_pct"] > 0:
            s["wins"] += 1
        s["pnl_sum"] += p["pnl_pct"]
    result["by_source"] = {
        src: {
            "trades": d["trades"], "wins": d["wins"],
            "win_rate": round(d["wins"] / max(d["trades"], 1), 3),
            "avg_pnl": round(d["pnl_sum"] / max(d["trades"], 1), 2),
            "total_pnl": round(d["pnl_sum"], 2),
        } for src, d in src_stats.items()
    }

    # by_symbol
    sym_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_sum": 0.0})
    for p in pairs:
        s = sym_stats[p["symbol"]]
        s["trades"] += 1
        if p["pnl_pct"] > 0:
            s["wins"] += 1
        s["pnl_sum"] += p["pnl_pct"]
    result["by_symbol"] = {
        sym: {
            "trades": d["trades"], "wins": d["wins"],
            "win_rate": round(d["wins"] / max(d["trades"], 1), 3),
            "total_pnl": round(d["pnl_sum"], 2),
        } for sym, d in sym_stats.items()
    }

    # by_source_symbol (交叉表)
    cross = defaultdict(lambda: defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}))
    for p in pairs:
        c = cross[p["source"]][p["symbol"]]
        c["trades"] += 1
        if p["pnl_pct"] > 0:
            c["wins"] += 1
        c["pnl"] += p["pnl_pct"]
    result["by_source_symbol"] = {
        src: {sym: {"trades": d["trades"], "wins": d["wins"], "pnl": round(d["pnl"], 2)}
              for sym, d in syms.items()}
        for src, syms in cross.items()
    }

    return result


# ============================================================
# KEY-009 券商对账: CSV实际交易 vs 系统信号匹配
# ============================================================

def _load_options_history() -> list:
    """读取 state/tsla_options_history.json (由 qqq_options.py 生成)"""
    try:
        _oh_path = ROOT / "state" / "tsla_options_history.json"
        if _oh_path.exists():
            return json.loads(_oh_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_broker_pnl() -> dict:
    """读取 state/broker_pnl.json (由 broker_reconciler.py 生成)"""
    try:
        _bp_path = ROOT / "state" / "broker_pnl.json"
        if _bp_path.exists():
            return json.loads(_bp_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _match_broker_trades(hours: int) -> dict:
    """????CSV (AIPro/XXXX-X306.CSV/.csv) ? trade_history.json ?????
    ???? state/broker_pnl.json ?? Coinbase fills ?????"""
    result = {
        "enabled": False,
        "sys_signals": 0, "actual_trades": 0,
        "sys_exec_rate": 0.0, "signal_coverage": 0.0,
        "no_signal_count": 0, "not_exec_count": 0,
        "matches": [],
        "no_signal": [],
        "by_source": {},
        "csv_path": "",
        "latest_trade_date": "",
        "latest_file_mtime": "",
        "coinbase_updated_at": "",
        "coinbase_products": 0,
        "coinbase_total_realized": 0.0,
        "reconcile_updated_at": "",
    }

    broker_pnl_path = ROOT / "state" / "broker_pnl.json"
    if broker_pnl_path.exists():
        try:
            broker_pnl = json.loads(broker_pnl_path.read_text(encoding="utf-8"))
            result["reconcile_updated_at"] = str(broker_pnl.get("updated_at", "") or "")
            cb = broker_pnl.get("coinbase", {}) or {}
            cb_symbols = cb.get("symbols", {}) or {}
            result["coinbase_updated_at"] = result["reconcile_updated_at"]
            result["coinbase_products"] = len(cb_symbols)
            result["coinbase_total_realized"] = float(cb.get("total_realized", 0.0) or 0.0)
        except Exception:
            pass

    csv_candidates = [
        ROOT / "AIPro" / "XXXX-X306.CSV",
        ROOT / "AIPro" / "XXXX-X306.csv",
        ROOT / ".GCC" / "doc" / "XXXX-X306.CSV",
        ROOT / ".GCC" / "doc" / "XXXX-X306.csv",
    ]
    csv_path = next((p for p in csv_candidates if p.exists()), None)
    if not csv_path:
        return result

    th_path = ROOT / "logs" / "trade_history.json"
    if not th_path.exists():
        return result

    result["enabled"] = True
    result["csv_path"] = str(csv_path)
    try:
        result["latest_file_mtime"] = datetime.fromtimestamp(csv_path.stat().st_mtime, NY_TZ).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        pass
    cutoff = datetime.now(NY_TZ) - timedelta(hours=hours)

    import csv as csv_mod
    csv_trades = []
    all_csv_trades = []
    try:
        with open(csv_path, encoding="utf-8") as f:
            for r in csv_mod.DictReader(f):
                if r.get("Action") not in ("Buy", "Sell"):
                    continue
                try:
                    dt = datetime.strptime(r["Date"], "%m/%d/%Y")
                    dt = dt.replace(hour=12, tzinfo=NY_TZ)
                except Exception:
                    continue
                price_str = r.get("Price", "0").replace("$", "").replace(",", "")
                amt_str = r.get("Amount", "0").replace("$", "").replace(",", "")
                try:
                    qty = int(float(r.get("Quantity", 0) or 0))
                except Exception:
                    qty = 0
                item = {
                    "date": r["Date"], "date_iso": dt.strftime("%Y-%m-%d"),
                    "action": r["Action"].upper(), "symbol": r["Symbol"],
                    "price": float(price_str or 0), "qty": qty,
                    "amount": float(amt_str or 0),
                }
                all_csv_trades.append(item)
                if dt >= cutoff:
                    csv_trades.append(item)
    except Exception:
        return result

    if all_csv_trades:
        try:
            result["latest_trade_date"] = max(t["date_iso"] for t in all_csv_trades)
        except Exception:
            pass

    if not csv_trades:
        return result

    try:
        sys_records = json.loads(th_path.read_text(encoding="utf-8"))
    except Exception:
        return result

    stock_syms = {c["symbol"] for c in csv_trades}
    sys_filtered = []
    for r in sys_records:
        if r.get("symbol") not in stock_syms or not r.get("ts"):
            continue
        try:
            ts = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY_TZ)
        except Exception:
            continue
        if ts < cutoff:
            continue
        sys_filtered.append({
            "ts": r["ts"], "date_iso": r["ts"][:10],
            "action": r.get("action", ""), "symbol": r["symbol"],
            "price": r.get("price", 0), "source": r.get("source", "?"),
        })

    matches = []
    for s in sys_filtered:
        best_match = None
        best_diff = 999
        for c in csv_trades:
            if c["date_iso"] == s["date_iso"] and c["symbol"] == s["symbol"] and c["action"] == s["action"]:
                diff = abs(c["price"] - s["price"]) / max(s["price"], 0.01) * 100
                if diff < best_diff:
                    best_diff = diff
                    best_match = c
        matches.append({
            "ts": s["ts"], "action": s["action"], "symbol": s["symbol"],
            "sys_price": round(s["price"], 2), "source": s["source"],
            "actual_price": round(best_match["price"], 2) if best_match else None,
            "price_diff_pct": round(best_diff, 2) if best_match else None,
            "matched": best_match is not None,
            "qty": best_match["qty"] if best_match else None,
            "amount": best_match["amount"] if best_match else None,
        })

    no_signal = []
    covered = []
    for c in csv_trades:
        has_signal = False
        matched_source = None
        for s in sys_filtered:
            if s["date_iso"] == c["date_iso"] and s["symbol"] == c["symbol"] and s["action"] == c["action"]:
                has_signal = True
                matched_source = s["source"]
                break
        if has_signal:
            covered.append({**c, "source": matched_source})
        else:
            no_signal.append(c)

    src_count = {}
    for s in sys_filtered:
        src_count[s["source"]] = src_count.get(s["source"], 0) + 1

    sys_exec = sum(1 for m in matches if m["matched"])
    result.update({
        "sys_signals": len(sys_filtered),
        "actual_trades": len(csv_trades),
        "sys_executed": sys_exec,
        "sys_exec_rate": round(sys_exec / max(len(sys_filtered), 1), 3),
        "signal_coverage": round(len(covered) / max(len(csv_trades), 1), 3),
        "no_signal_count": len(no_signal),
        "not_exec_count": len(sys_filtered) - sys_exec,
        "matches": matches,
        "no_signal": no_signal,
        "by_source": src_count,
    })
    return result

def _validate_blocks(hours: int) -> dict:
    """验证signal_decisions中被拦截信号事后是否正确。
    用trade_history.json同symbol后续价格做近似比对。"""
    result = {
        "total_blocked": 0, "validated": 0,
        "correct": 0, "incorrect": 0, "accuracy": 0.0,
        "by_reason": {}, "by_source": {},
    }
    sd_path = ROOT / "logs" / "signal_decisions.jsonl"
    th_path = ROOT / "logs" / "trade_history.json"
    if not sd_path.exists() or not th_path.exists():
        return result

    cutoff = datetime.now(NY_TZ) - timedelta(hours=hours)

    # 加载trade_history作为价格参考(按symbol排序好的时间序列)
    try:
        trades = json.loads(th_path.read_text(encoding="utf-8"))
    except Exception:
        return result
    # 构建symbol→[(ts, price)] lookup
    price_timeline = defaultdict(list)
    for t in trades:
        try:
            ts = datetime.strptime(t["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY_TZ)
            price_timeline[t["symbol"]].append((ts, t["price"]))
        except Exception:
            continue
    for sym in price_timeline:
        price_timeline[sym].sort(key=lambda x: x[0])

    # 读取被拦截的信号
    blocked = []
    try:
        with open(sd_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("allowed"):
                    continue
                try:
                    ts = datetime.fromisoformat(rec["ts"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=NY_TZ)
                    if ts < cutoff:
                        continue
                except Exception:
                    continue
                if not rec.get("price"):
                    continue
                blocked.append({
                    "ts": ts, "symbol": rec["symbol"],
                    "action": rec.get("action", ""),
                    "price": rec["price"],
                    "reason": rec.get("reason", ""),
                    "source": rec.get("signal_source", "unknown"),
                })
    except Exception:
        return result

    result["total_blocked"] = len(blocked)
    if not blocked:
        return result

    # 验证: 找拦截后4H内最近的后续价格
    reason_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    source_stats = defaultdict(lambda: {"total": 0, "correct": 0})

    for b in blocked:
        sym = b["symbol"]
        timeline = price_timeline.get(sym, [])
        if not timeline:
            continue

        # 找拦截后4H窗口内的价格
        window_end = b["ts"] + timedelta(hours=4)
        future_prices = [p for ts, p in timeline if b["ts"] < ts <= window_end]
        if not future_prices:
            continue

        # 取4H后最后一个价格
        later_price = future_prices[-1]
        result["validated"] += 1

        # 判定: BUY被拦截 → 后续涨了=拦截错误(错过机会), 跌了=拦截正确
        #        SELL被拦截 → 后续跌了=拦截错误(应该卖), 涨了=拦截正确
        price_change_pct = (later_price - b["price"]) / b["price"] * 100
        threshold = 0.5  # 0.5%以内算中性,不计入

        if abs(price_change_pct) < threshold:
            continue  # 中性, 不计入正确/错误

        if b["action"] == "BUY":
            is_correct = price_change_pct < 0  # 跌了=拦截正确
        elif b["action"] == "SELL":
            is_correct = price_change_pct > 0  # 涨了=拦截正确
        else:
            continue

        if is_correct:
            result["correct"] += 1
        else:
            result["incorrect"] += 1

        # 提取拦截原因的前缀关键词
        reason_key = _extract_block_reason(b["reason"])
        reason_stats[reason_key]["total"] += 1
        if is_correct:
            reason_stats[reason_key]["correct"] += 1

        source_stats[b["source"]]["total"] += 1
        if is_correct:
            source_stats[b["source"]]["correct"] += 1

    decisive = result["correct"] + result["incorrect"]
    result["accuracy"] = round(result["correct"] / max(decisive, 1), 3)

    result["by_reason"] = {
        k: {"total": v["total"], "correct": v["correct"],
            "accuracy": round(v["correct"] / max(v["total"], 1), 3)}
        for k, v in reason_stats.items()
    }
    result["by_source"] = {
        k: {"total": v["total"], "correct": v["correct"],
            "accuracy": round(v["correct"] / max(v["total"], 1), 3)}
        for k, v in source_stats.items()
    }
    return result


def _extract_block_reason(reason: str) -> str:
    """从拦截reason字符串提取核心原因类别。"""
    if not reason:
        return "未知"
    r = reason
    if "EMA" in r or "ema" in r:
        return "EMA价格过滤"
    if "仓位" in r or "满仓" in r or "档" in r:
        return "仓位控制"
    if "方向" in r or "bias" in r.lower() or "只做" in r:
        return "方向限制"
    if "冷却" in r or "限次" in r or "去重" in r:
        return "冷却/限次"
    if "门控" in r or "GATE" in r or "N_GATE" in r:
        return "门控拦截"
    if "FilterChain" in r or "FILTER" in r:
        return "FilterChain"
    if "Vision" in r or "vision" in r:
        return "Vision过滤"
    if "清仓" in r:
        return "清仓条件"
    if "合并" in r or "body" in r:
        return "K线形态"
    return reason[:15] if len(reason) > 15 else reason


# ============================================================
# KEY-009 Phase2: 策略排行
# ============================================================

def _rank_strategies(trade_stats: dict, block_stats: dict) -> list:
    """综合评分排行 → 加强/降低建议。"""
    ranking = []
    by_source = trade_stats.get("by_source", {})
    block_by_source = block_stats.get("by_source", {})

    for source, stats in by_source.items():
        trades = stats.get("trades", 0)
        win_rate = stats.get("win_rate", 0)
        avg_pnl = stats.get("avg_pnl", 0)
        total_pnl = stats.get("total_pnl", 0)

        # 盈利因子: avg_pnl归一化到0-100
        pnl_score = max(0, min(100, 50 + avg_pnl * 10))  # ±5% → 0~100

        # 拦截合理度: 该外挂被拦截的正确率
        block_info = block_by_source.get(source, {})
        block_acc = block_info.get("accuracy", 0.5) if block_info.get("total", 0) >= 3 else 0.5

        # 综合评分 = 胜率×40 + 盈亏×30 + 交易量×10 + 拦截合理度×20
        vol_score = min(100, trades * 10)  # 10笔=满分
        score = (win_rate * 100 * 0.4 +
                 pnl_score * 0.3 +
                 vol_score * 0.1 +
                 block_acc * 100 * 0.2)

        if trades < 3:
            action = "观察"
        elif score > 70:
            action = "加强"
        elif score >= 50:
            action = "维持"
        else:
            action = "降低频次"

        ranking.append({
            "rank": 0,
            "source": source,
            "trades": trades,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_pnl": total_pnl,
            "score": round(score, 1),
            "action": action,
            "block_total": block_info.get("total", 0),
            "block_accuracy": block_info.get("accuracy", 0),
        })

    ranking.sort(key=lambda x: -x["score"])
    for i, r in enumerate(ranking):
        r["rank"] = i + 1

    return ranking


# ============================================================
# KEY-009 闭环: 经验卡回写 + 结构化规则生成
# ============================================================

def _gcc_evo_imports():
    """导入 gcc-evo 模块（优先 .GCC 下的新版）。"""
    import sys
    gcc_path = str(ROOT / ".GCC")
    if gcc_path not in sys.path:
        sys.path.insert(0, gcc_path)
    from gcc_evolution.models import ExperienceCard, ExperienceType
    from gcc_evolution.experience_store import GlobalMemory
    try:
        from gcc_evolution.models import KnowledgeBank
        kb_case = KnowledgeBank.CASE.value
    except ImportError:
        kb_case = "case"
    return ExperienceCard, ExperienceType, GlobalMemory, kb_case


def _generate_experience_cards(fifo_trades: dict, block_validation: dict,
                                strategy_ranking: list, hours: int) -> list:
    """从审计结果生成 gcc-evo ExperienceCard dict 列表。
    v5.295: 加入信号准确率(4H回填)维度, 提升卡片精度。"""
    try:
        ExperienceCard, ExperienceType, _, kb_case = _gcc_evo_imports()
    except ImportError:
        return []

    cards = []
    now_str = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M")

    # v5.295: 加载信号准确率数据
    _sig_acc = {}
    try:
        if PLUGIN_SIGNAL_STATE.exists():
            _sig_data = json.loads(PLUGIN_SIGNAL_STATE.read_text(encoding="utf-8"))
            _sig_acc = _sig_data.get("accuracy", {})
    except Exception:
        pass

    # ── 按外挂: 每个>=5笔交易的外挂一张卡 ──
    by_source = fifo_trades.get("by_source", {})
    for source, stats in by_source.items():
        trades = stats.get("trades", 0)
        if trades < 5:
            continue
        win_rate = stats.get("win_rate", 0)
        avg_pnl = stats.get("avg_pnl", 0)

        # v5.295: 信号准确率增强
        src_acc = _sig_acc.get(source, {}).get("_overall", {})
        signal_acc = src_acc.get("acc")  # None if no data
        signal_decisive = src_acc.get("total", 0)

        if win_rate >= 0.6:
            exp_type = ExperienceType.SUCCESS
        elif win_rate >= 0.4:
            exp_type = ExperienceType.PARTIAL
        else:
            exp_type = ExperienceType.FAILURE

        # v5.295: insight加入信号准确率
        insight = f"{source}: 胜率{win_rate:.0%}, 均盈{avg_pnl:+.2f}%, 总盈{stats.get('total_pnl', 0):+.2f}%"
        if signal_acc is not None and signal_decisive >= 5:
            insight += f", 信号准确率{signal_acc:.0%}({signal_decisive}笔4H回填)"

        # v5.295: metrics加入信号准确率
        metrics = {"win_rate": win_rate, "avg_pnl": avg_pnl,
                   "trades": trades, "total_pnl": stats.get("total_pnl", 0)}
        if signal_acc is not None:
            metrics["signal_acc"] = signal_acc
            metrics["signal_decisive"] = signal_decisive

        # v5.295: confidence加入信号准确率权重
        conf = win_rate * 0.5 + min(trades, 20) / 20 * 0.2
        if signal_acc is not None and signal_decisive >= 5:
            conf += signal_acc * 0.3
        else:
            conf += 0.15  # 无数据时给中性权重

        card = ExperienceCard(
            source_session=f"key009_audit_{now_str}",
            exp_type=exp_type,
            trigger_task_type="key009_strategy_perf",
            trigger_symptom=f"{source} {hours}h绩效: {trades}笔 胜率{win_rate:.0%}",
            trigger_keywords=[source, "key009", "fifo", "signal_accuracy"],
            strategy=f"外挂{source}在{hours}h内交易{trades}笔",
            key_insight=insight,
            metrics_after=metrics,
            confidence=round(min(1.0, conf), 3),
            key="KEY-009",
            tags=["key009", "strategy_perf", source],
            knowledge_bank=kb_case,
        )
        cards.append(card)

    # ── 拦截验证卡 ──
    validated = block_validation.get("validated", 0)
    if validated >= 5:
        acc = block_validation.get("accuracy", 0)
        card = ExperienceCard(
            source_session=f"key009_audit_{now_str}",
            exp_type=ExperienceType.SUCCESS if acc >= 0.6 else ExperienceType.PARTIAL,
            trigger_task_type="key009_block_validation",
            trigger_symptom=f"拦截验证{validated}次, 准确率{acc:.0%}",
            trigger_keywords=["block_validation", "key009"],
            strategy=f"{hours}h内验证{validated}次拦截决策",
            key_insight=f"拦截准确率{acc:.0%} ({block_validation.get('correct',0)}正确/{block_validation.get('incorrect',0)}错误)",
            metrics_after={"accuracy": acc, "validated": validated,
                           "correct": block_validation.get("correct", 0),
                           "incorrect": block_validation.get("incorrect", 0)},
            confidence=round(min(1.0, acc * 0.6 + min(validated, 30) / 30 * 0.4), 3),
            key="KEY-009",
            tags=["key009", "block_validation"],
            knowledge_bank=kb_case,
        )
        cards.append(card)

    return cards


def _save_cards_to_store(cards: list) -> int:
    """写入 gcc-evo GlobalMemory (自动去重+质量门控)。"""
    if not cards:
        return 0
    try:
        _, _, GlobalMemory, _ = _gcc_evo_imports()
    except ImportError:
        return 0
    saved = 0
    try:
        gm = GlobalMemory()
        for card in cards:
            passed, _ = gm.store_with_gate(card)
            if passed:
                saved += 1
    except Exception as e:
        print(f"[KEY009] 经验卡写入失败: {e}")
    return saved


def _extract_rules(strategy_ranking: list, block_validation: dict) -> list:
    """从策略排行+拦截验证生成 gcc-evo 兼容规则列表。"""
    rules = []
    rule_idx = 1

    # ── 策略排行 → 规则 ──
    action_map = {"加强": "RELAX", "维持": "OBSERVE", "降低频次": "TIGHTEN", "观察": "OBSERVE"}
    for r in strategy_ranking:
        if r.get("trades", 0) < 5:
            continue
        rule_id = f"KEY-009-R{rule_idx:03d}"
        rule_idx += 1
        win_rate = r.get("win_rate", 0)
        block_acc = r.get("block_accuracy", 0.5)
        conf = round(win_rate * 0.6 + block_acc * 0.4, 3)
        rules.append({
            "rule_id": rule_id,
            "key": "KEY-009",
            "trigger_condition": f"source={r['source']}",
            "action": action_map.get(r.get("action", ""), "OBSERVE"),
            "recommendation": f"{r['source']}: {r.get('action','')} (评分{r.get('score',0):.0f})",
            "confidence": conf,
            "sample_count": r.get("trades", 0),
            "win_rate": win_rate,
            "valid_rate": block_acc,
            "status": "DISCOVERED",
        })

    # ── 拦截原因 → 规则 ──
    by_reason = block_validation.get("by_reason", {})
    for reason, info in by_reason.items():
        total = info.get("total", 0)
        if total < 5:
            continue
        acc = info.get("accuracy", 0.5)
        rule_id = f"KEY-009-R{rule_idx:03d}"
        rule_idx += 1
        if acc >= 0.6:
            action = "OBSERVE"  # 有效保留
        elif acc < 0.35:
            action = "RELAX"   # 放宽
        else:
            action = "REVIEW"
        rules.append({
            "rule_id": rule_id,
            "key": "KEY-009",
            "trigger_condition": f"block_reason={reason}",
            "action": action,
            "recommendation": f"拦截原因'{reason}': 准确率{acc:.0%} ({total}次)",
            "confidence": round(acc, 3),
            "sample_count": total,
            "win_rate": 0.0,
            "valid_rate": acc,
            "status": "DISCOVERED",
        })

    return rules


def _save_rules(rules: list) -> None:
    """写入 state/key009_rules.json + RuleRegistry。"""
    if not rules:
        return
    # ── 写 state JSON (供主程序消费) ──
    out_path = STATE_DIR / "key009_rules.json"
    fallback_path = STATE_DIR / "key009_rules.latest.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": "KEY-009",
        "generated_at": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M"),
        "rules": rules,
    }
    _raw = json.dumps(payload, ensure_ascii=False, indent=2)
    _rule_written = False
    for _path in (out_path, fallback_path):
        try:
            _path.write_text(_raw, encoding="utf-8")
            _rule_written = True
            break
        except Exception as e:
            logger.warning("[KEY009] rules write failed: %s -> %s", _path.name, e)
    if not _rule_written:
        return

    # ── 写入 RuleRegistry (生命周期管理) ──
    try:
        import sys as _sys_r
        gcc_path = str(ROOT / ".GCC")
        if gcc_path not in _sys_r.path:
            _sys_r.path.insert(0, gcc_path)
        from gcc_evolution.rule_registry import RuleRegistry
        registry = RuleRegistry()
        registry.ingest_from_retrospective(payload)
    except ImportError:
        pass
    except Exception as e:
        print(f"[KEY009] RuleRegistry写入失败: {e}")


def rule_transition(rule_id: str, new_status: str) -> dict:
    """L5: 规则状态转换 DISCOVERED→ACTIVE→DEPRECATED。
    返回 {"ok": bool, "rule_id": str, "old_status": str, "new_status": str}
    """
    valid = {"DISCOVERED", "ACTIVE", "DEPRECATED"}
    if new_status not in valid:
        return {"ok": False, "error": f"Invalid status: {new_status}"}
    rules_path = STATE_DIR / "key009_rules.json"
    if not rules_path.exists():
        return {"ok": False, "error": "rules file not found"}
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    found = False
    old_status = ""
    for r in rules:
        if r.get("rule_id") == rule_id:
            old_status = r.get("status", "DISCOVERED")
            r["status"] = new_status
            r["status_changed_at"] = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M")
            found = True
            break
    if not found:
        return {"ok": False, "error": f"rule {rule_id} not found"}
    rules_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "rule_id": rule_id, "old_status": old_status, "new_status": new_status}


# ============================================================
# GCC-0197 S2: 外挂信号准确率回填
# ============================================================
PLUGIN_SIGNAL_STATE = STATE_DIR / "plugin_signal_accuracy.json"


def _lookup_trade_price(symbol: str, ts_str: str) -> float:
    """从trade_history.json查找同品种同时间±30min内最近的价格。price=0时的后备方案。"""
    th_path = ROOT / "logs" / "trade_history.json"
    if not th_path.exists():
        return 0.0
    try:
        trades = json.loads(th_path.read_text(encoding="utf-8"))
        sig_ts = datetime.fromisoformat(ts_str)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.replace(tzinfo=NY_TZ)
        best_price = 0.0
        best_diff = 1800  # 30分钟内
        for t in trades:
            if t.get("symbol") != symbol or not t.get("price"):
                continue
            try:
                t_ts = datetime.strptime(t["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY_TZ)
                diff = abs((t_ts - sig_ts).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_price = t["price"]
            except Exception:
                continue
        return best_price
    except Exception:
        return 0.0


def _plugin_accuracy_backfill(new_signals: list) -> dict:
    """GCC-0197 S2: 合并新dispatch信号 → 4H后回填价格 → 统计准确率。
    返回 {source: {symbol: {total, correct, incorrect, pending, acc}}}
    """
    # 加载已有状态
    state = {"signals": [], "accuracy": {}}
    try:
        if PLUGIN_SIGNAL_STATE.exists():
            state = json.loads(PLUGIN_SIGNAL_STATE.read_text(encoding="utf-8"))
    except Exception:
        pass

    signals = state.get("signals", [])

    # 合并新信号 (去重: ts+symbol+source)
    existing_keys = {(s["ts"], s["symbol"], s["source"]) for s in signals}
    for ns in new_signals:
        key = (ns["ts"], ns["symbol"], ns["source"])
        if key not in existing_keys:
            ns["result"] = "pending"
            ns["current_price"] = None
            signals.append(ns)
            existing_keys.add(key)

    # 4H回填: 对pending信号且已超4H的, 尝试获取当前价格
    now = datetime.now(NY_TZ)
    backfill_count = 0
    for sig in signals:
        if sig.get("result") != "pending":
            continue
        try:
            sig_ts = datetime.fromisoformat(sig["ts"])
            if sig_ts.tzinfo is None:
                sig_ts = sig_ts.replace(tzinfo=NY_TZ)
            hours_elapsed = (now - sig_ts).total_seconds() / 3600
            if hours_elapsed < 4:
                continue  # 未满4H
            if hours_elapsed > 168:
                sig["result"] = "expired"  # 超7天，标记过期
                continue
        except Exception:
            continue

        # 获取信号发出4H后的历史价格 (非实时价格)
        eval_ts = sig_ts + timedelta(hours=4)
        if eval_ts > now:
            continue  # 还没到评估时间
        _cur_price = _get_price_at_time(sig["symbol"], eval_ts)
        # 回退: 历史价格取不到时用实时价格(仅信号>24H时)
        if (not _cur_price or _cur_price <= 0) and hours_elapsed > 24:
            _cur_price = _get_current_price_safe(sig["symbol"])
        if _cur_price and _cur_price > 0:
            sig["current_price"] = _cur_price
            sig["eval_ts"] = eval_ts.isoformat()
            entry_price = sig.get("price", 0)
            # price=0时: 从trade_history查找同品种同时间附近的价格作为entry_price
            if not entry_price:
                entry_price = _lookup_trade_price(sig["symbol"], sig["ts"])
                if entry_price > 0:
                    sig["price"] = entry_price  # 回补price
            if entry_price > 0:
                pct_change = (_cur_price - entry_price) / entry_price
                if sig["action"] == "BUY":
                    sig["result"] = "CORRECT" if pct_change > 0.001 else ("INCORRECT" if pct_change < -0.001 else "NEUTRAL")
                elif sig["action"] == "SELL":
                    sig["result"] = "CORRECT" if pct_change < -0.001 else ("INCORRECT" if pct_change > 0.001 else "NEUTRAL")
                sig["pct_change"] = round(pct_change * 100, 2)
                backfill_count += 1

    # 统计准确率: 按source×symbol
    accuracy = defaultdict(lambda: defaultdict(lambda: {"total": 0, "correct": 0, "incorrect": 0, "neutral": 0, "pending": 0}))
    for sig in signals:
        src = sig.get("source", "?")
        sym = sig.get("symbol", "?")
        r = sig.get("result", "pending")
        if r == "CORRECT":
            accuracy[src][sym]["correct"] += 1
            accuracy[src][sym]["total"] += 1
        elif r == "INCORRECT":
            accuracy[src][sym]["incorrect"] += 1
            accuracy[src][sym]["total"] += 1
        elif r == "NEUTRAL":
            accuracy[src][sym]["neutral"] += 1
            accuracy[src][sym]["total"] += 1
        elif r == "pending":
            accuracy[src][sym]["pending"] += 1

    # 计算acc
    acc_result = {}
    for src, syms in accuracy.items():
        acc_result[src] = {}
        src_total = src_correct = 0
        for sym, d in syms.items():
            decisive = d["correct"] + d["incorrect"]
            d["acc"] = round(d["correct"] / decisive, 3) if decisive > 0 else None
            acc_result[src][sym] = dict(d)
            src_total += decisive
            src_correct += d["correct"]
        acc_result[src]["_overall"] = {
            "total": src_total,
            "correct": src_correct,
            "acc": round(src_correct / src_total, 3) if src_total > 0 else None,
        }

    # 保存状态 (只保留7天内的信号)
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    signals = [s for s in signals if s.get("ts", "") > cutoff_7d]
    state["signals"] = signals
    state["accuracy"] = {src: {sym: dict(d) for sym, d in syms.items()} for src, syms in acc_result.items()}
    state["last_backfill"] = now.isoformat()
    state["backfill_count"] = backfill_count

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PLUGIN_SIGNAL_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return acc_result


# ============================================================
# GCC-0197 S3: 外挂Phase升降级
# ============================================================
PLUGIN_PHASE_STATE = STATE_DIR / "plugin_phase_state.json"

# 阈值
_PHASE_DOWN_ACC = 0.50    # 准确率<50% → 降级
_PHASE_UP_ACC = 0.55      # 准确率>=55% → 恢复
_PHASE_MIN_DECISIVE = 30  # 最少需要30个decisive样本


def _plugin_phase_update(plugin_accuracy: dict) -> dict:
    """GCC-0197 S3: 按品种×外挂Phase升降级。
    decisive>=30 且 acc<50% → DOWNGRADE(TIGHTEN), acc>=55% → RESTORE(OBSERVE)。
    返回 {source: {phase, acc, decisive, changed_at, action}}。
    """
    # 加载已有phase状态
    phases = {}
    try:
        if PLUGIN_PHASE_STATE.exists():
            phases = json.loads(PLUGIN_PHASE_STATE.read_text(encoding="utf-8"))
    except Exception:
        pass

    now_str = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M")
    changed = False

    for src, syms in plugin_accuracy.items():
        overall = syms.get("_overall", {})
        total = overall.get("total", 0)
        acc = overall.get("acc")
        if acc is None or total < _PHASE_MIN_DECISIVE:
            continue

        prev = phases.get(src, {})
        prev_phase = prev.get("phase", "NORMAL")

        if acc < _PHASE_DOWN_ACC and prev_phase != "DOWNGRADED":
            phases[src] = {
                "phase": "DOWNGRADED",
                "acc": acc,
                "decisive": total,
                "changed_at": now_str,
                "action": "TIGHTEN",
                "prev_phase": prev_phase,
            }
            changed = True
        elif acc >= _PHASE_UP_ACC and prev_phase == "DOWNGRADED":
            phases[src] = {
                "phase": "NORMAL",
                "acc": acc,
                "decisive": total,
                "changed_at": now_str,
                "action": "RESTORED",
                "prev_phase": prev_phase,
            }
            changed = True
        else:
            # 更新acc但不改phase
            if src in phases:
                phases[src]["acc"] = acc
                phases[src]["decisive"] = total
            else:
                phases[src] = {
                    "phase": "NORMAL",
                    "acc": acc,
                    "decisive": total,
                    "changed_at": now_str,
                    "action": "OBSERVE",
                }

    if changed:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            PLUGIN_PHASE_STATE.write_text(
                json.dumps(phases, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return phases


def _get_price_at_time(symbol: str, target_ts: "datetime") -> float:
    """获取指定时间点的历史价格 (yfinance 1H K线)。
    用于信号准确率回填: 取 target_ts 附近最近的收盘价。
    v3.679: 美股盘后时间(16:00-09:30 ET)跳过yfinance请求，避免大量"possibly delisted"错误
    """
    try:
        import yfinance as yf
        # 品种映射: BTCUSDC → BTC-USD, TSLA → TSLA
        yf_symbol = symbol
        is_crypto = symbol.endswith("USDC") or symbol.endswith("USDT")
        if symbol.endswith("USDC"):
            yf_symbol = symbol[:-4] + "-USD"
        elif symbol.endswith("USDT"):
            yf_symbol = symbol[:-4] + "-USD"

        # v3.679: 美股盘后时间跳过 — yfinance对盘后1h数据返回空
        if not is_crypto:
            _eval_hour = target_ts.hour if target_ts.tzinfo else target_ts.replace(tzinfo=NY_TZ).hour
            if _eval_hour >= 16 or _eval_hour < 9 or (_eval_hour == 9 and target_ts.minute < 30):
                return 0.0

        # 取 target_ts 前后各1H 的数据窗口
        start = target_ts - timedelta(hours=1)
        end = target_ts + timedelta(hours=1)
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=start, end=end, interval="1h")
        if df.empty:
            return 0.0
        # 取最接近 target_ts 的行
        df.index = df.index.tz_convert("US/Eastern") if df.index.tz else df.index.tz_localize("US/Eastern")
        target_aware = target_ts if target_ts.tzinfo else target_ts.replace(tzinfo=NY_TZ)
        closest_idx = min(df.index, key=lambda t: abs((t - target_aware).total_seconds()))
        return float(df.loc[closest_idx, "Close"])
    except Exception:
        return 0.0


def _get_current_price_safe(symbol: str) -> float:
    """安全获取品种当前价格 (从tracking state JSON)。"""
    # 先尝试tracking state (由llm_server持续更新)
    candidates = [symbol]
    if symbol.endswith("USDC"):
        base = symbol[:-4]
        candidates.extend([f"{base}-USD", f"{base}USD"])
    elif symbol.endswith("-USD"):
        base = symbol[:-4]
        candidates.extend([f"{base}USDC", f"{base}USD"])
    elif symbol.endswith("USD"):
        base = symbol[:-3]
        candidates.extend([f"{base}USDC", f"{base}-USD"])
    candidates = list(dict.fromkeys(candidates))

    for suffix in ["", "-BaoPCS", "-MSI"]:
        ts_path = ROOT / f"l2_10m_state{suffix}.json"
        try:
            if ts_path.exists():
                data = json.loads(ts_path.read_text(encoding="utf-8"))
                symbol_maps = [data]
                if isinstance(data, dict) and isinstance(data.get("symbols"), dict):
                    symbol_maps.append(data["symbols"])
                for symbol_map in symbol_maps:
                    for candidate in candidates:
                        sym_data = symbol_map.get(candidate, {})
                        if not isinstance(sym_data, dict):
                            continue
                        price = (
                            sym_data.get("last_price", 0)
                            or sym_data.get("current_price", 0)
                            or sym_data.get("last_close", 0)
                        )
                        if price and price > 0:
                            return float(price)
        except Exception:
            continue

    # 回退: 从plugin_profit_state的open_positions
    pp_path = ROOT / "state" / "plugin_profit_state.json"
    try:
        if pp_path.exists():
            data = json.loads(pp_path.read_text(encoding="utf-8"))
            open_entries = data.get("open_entries", {})
            if isinstance(open_entries, dict):
                for candidate in candidates:
                    for pos in open_entries.get(candidate, []):
                        if not isinstance(pos, dict):
                            continue
                        price = pos.get("current_price", 0) or pos.get("price", 0)
                        if price and price > 0:
                            return float(price)
            for pos in data.get("open_positions", []):
                if pos.get("symbol") in candidates:
                    price = pos.get("current_price", 0) or pos.get("price", 0)
                    if price and price > 0:
                        return float(price)
    except Exception:
        pass

    return 0.0


# ============================================================
# GCC-0202: 五层进化 — 系统评分 + 协作问题检测
# ============================================================

BASELINE_THRESHOLDS = {
    "win_rate": 50,      # 胜率基准 50%
    "errors": 80,        # 错误分 80+ = 低错误率
    "exec_eff": 30,      # 执行效率 30%+
    "stability": 90,     # 稳定性 90+
}


def _calc_win_rate_score(trade_analysis: dict) -> float:
    """S01: 从completed_trades算胜率, 归一化0-100。"""
    wr = trade_analysis.get("win_rate", 0)
    if isinstance(wr, (int, float)):
        return round(min(wr * 100, 100), 1)  # 0.45 → 45.0
    return 0.0


def _calc_error_score(tasks: dict, issues: list) -> float:
    """S02: 4h窗口ERROR/异常行数, 反比归一化(0错=100, 10+错=0)。"""
    error_count = sum(1 for iss in issues if iss.get("type") == "ERROR")
    error_count += sum(t.get("errors", 0) for t in tasks.values())
    # 0错=100, 每个错误-10, 下限0
    return max(0, 100 - error_count * 10)


def _calc_execution_efficiency(scan_plugins: dict, plugin_exec: dict) -> float:
    """S03: 外挂触发→实际下单比率, 含gate通过率。"""
    total_trigger = sum(p.get("trigger", 0) for p in scan_plugins.values())
    total_exec = sum(p.get("executed", 0) for p in scan_plugins.values())
    # 也考虑主程序外挂执行
    total_trigger += plugin_exec.get("sent", 0) + plugin_exec.get("skip", 0) + plugin_exec.get("block", 0)
    total_exec += plugin_exec.get("sent", 0)
    if total_trigger == 0:
        return 50.0  # 无数据→中性
    return round(total_exec / total_trigger * 100, 1)


def _calc_stability_score(issues: list, hours: int) -> float:
    """S04: 连续4h无crash/restart=100, 每次restart-20。"""
    restart_count = sum(1 for iss in issues
                        if "restart" in iss.get("msg", "").lower()
                        or "crash" in iss.get("msg", "").lower()
                        or "未运行" in iss.get("msg", ""))
    return max(0, 100 - restart_count * 20)


def _calc_system_score(trade_analysis: dict, tasks: dict, issues: list,
                       scan_plugins: dict, plugin_exec: dict, hours: int) -> dict:
    """S05: 4维加权(各0.25)返回总分 + 子分 + 基准达标。"""
    win = _calc_win_rate_score(trade_analysis)
    err = _calc_error_score(tasks, issues)
    exc = _calc_execution_efficiency(scan_plugins, plugin_exec)
    stb = _calc_stability_score(issues, hours)
    total = round(win * 0.25 + err * 0.25 + exc * 0.25 + stb * 0.25, 1)
    baselines = {
        "win_rate": {"value": win, "threshold": BASELINE_THRESHOLDS["win_rate"], "met": win >= BASELINE_THRESHOLDS["win_rate"]},
        "errors": {"value": err, "threshold": BASELINE_THRESHOLDS["errors"], "met": err >= BASELINE_THRESHOLDS["errors"]},
        "exec_eff": {"value": exc, "threshold": BASELINE_THRESHOLDS["exec_eff"], "met": exc >= BASELINE_THRESHOLDS["exec_eff"]},
        "stability": {"value": stb, "threshold": BASELINE_THRESHOLDS["stability"], "met": stb >= BASELINE_THRESHOLDS["stability"]},
    }
    return {"score": total, "win_rate": win, "errors": err, "exec_eff": exc, "stability": stb, "baselines": baselines}


def _detect_collaboration_issues(scan_plugins: dict, tasks: dict, issues: list,
                                 gates: dict, gate_totals: dict) -> list:
    """S07-S12: 协作问题检测。"""
    collab = []

    # S07: 外挂触发高但gate拦截率>90%
    for pname, pdata in scan_plugins.items():
        trigger = pdata.get("trigger", 0)
        executed = pdata.get("executed", 0)
        if trigger >= 3 and executed == 0:
            collab.append({"type": "PLUGIN_GATE_CONFLICT", "severity": "HIGH",
                           "detail": f"{pname} 触发{trigger}次但0执行, gate全拦截"})
        elif trigger >= 5 and executed / trigger < 0.1:
            collab.append({"type": "PLUGIN_GATE_CONFLICT", "severity": "MEDIUM",
                           "detail": f"{pname} 触发{trigger}次仅{executed}执行({executed/trigger:.0%})"})

    # S08: DATA-STALE占总issue比>50%
    total_issues = len([i for i in issues if i.get("type") not in ("POSITIVE",)])
    stale_count = sum(1 for i in issues if "DATA-STALE" in i.get("task", "") or "DATA-STALE" in i.get("msg", ""))
    if total_issues >= 3 and stale_count / total_issues > 0.5:
        collab.append({"type": "DATA_QUALITY_ISSUE", "severity": "HIGH",
                       "detail": f"DATA-STALE占{stale_count}/{total_issues}({stale_count/total_issues:.0%}), 数据源不稳定"})

    # S09: GCC任务全ERROR(0成功)
    error_tasks = [tid for tid, t in tasks.items() if t.get("status") == "ERROR"]
    ok_tasks = [tid for tid, t in tasks.items() if t.get("status") == "OK"]
    if error_tasks and not ok_tasks:
        collab.append({"type": "TASK_FAILURE_ISSUE", "severity": "CRITICAL",
                       "detail": f"全部GCC任务异常: {', '.join(error_tasks)}"})

    # S10: 信号翻转检测(从issues中提取)
    flip_issues = [i for i in issues if "翻转" in i.get("msg", "") or "FLIP" in i.get("msg", "").upper()]
    if len(flip_issues) >= 2:
        collab.append({"type": "FLIP_ISSUE", "severity": "MEDIUM",
                       "detail": f"检测到{len(flip_issues)}次信号翻转问题"})

    return collab


def _parse_evolution_memory() -> list:
    """S18-S21: 解析evolution-log.md → 最近10条记忆。"""
    evo_path = ROOT / ".GCC" / "skill" / "evolution-log.md"
    if not evo_path.exists():
        return []
    try:
        text = evo_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    def _repair_mojibake_text(value: str) -> str:
        if not isinstance(value, str) or not value:
            return value

        def _score(s: str) -> int:
            cjk = len(re.findall(r"[\u3400-\u9fff]", s))
            bad = len(re.findall(r"[ÃÂâ€œâ€â€™â€”çåäéèêëï¼½œ™]", s))
            return cjk * 2 - bad * 3

        best = value
        best_score = _score(value)
        for codec in ("cp1252", "latin1"):
            current = value
            for _ in range(2):
                try:
                    candidate = current.encode(codec, errors="ignore").decode("utf-8", errors="ignore").replace("\x00", "").strip()
                except Exception:
                    break
                if not candidate or candidate == current:
                    break
                cand_score = _score(candidate)
                if cand_score > best_score:
                    best = candidate
                    best_score = cand_score
                current = candidate
        return best

    entries = []
    pattern = re.compile(r"###\s+(?:\[(\d{4}-\d{2}-\d{2})\]|(\d{4}-\d{2}-\d{2}))\s+\[([^\]]+)\]\s+(.*)")
    current = None
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            if current:
                entries.append(current)
            entry_date = m.group(1) or m.group(2)
            current = {"date": entry_date, "priority": m.group(3), "title": _repair_mojibake_text(m.group(4).strip()),
                        "fields": {}}
        elif current and line.startswith("- **") and "**:" in line:
            # 提取 场景/问题/解决方案/代码位置/教训
            key_match = re.match(r"- \*\*(.+?)\*\*:\s*(.*)", line)
            if key_match:
                current["fields"][_repair_mojibake_text(key_match.group(1))] = _repair_mojibake_text(key_match.group(2).strip())
    if current:
        entries.append(current)

    # 按日期倒排取最近10条
    entries.sort(key=lambda x: x["date"], reverse=True)
    return entries[:10]


def _append_evo_history(scores: dict) -> str:
    """S23-S28: 每4h追加到system_evo_history.jsonl + 计算trend。"""
    hist_path = STATE_DIR / "system_evo_history.jsonl"
    now_ny = datetime.now(NY_TZ)
    slot = ((now_ny.hour - 8) % 24) // 4

    record = {
        "ts": now_ny.strftime("%Y-%m-%dT%H:%M"),
        "slot": slot,
        "score": scores.get("score", 0),
        "win_rate": scores.get("win_rate", 0),
        "errors": scores.get("errors", 0),
        "exec_eff": scores.get("exec_eff", 0),
        "stability": scores.get("stability", 0),
    }

    # 追加
    try:
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # 读全部计算trend
    history = []
    try:
        if hist_path.exists():
            for line in hist_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        history.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass

    # 文件轮转: 超过180条保留最近180
    if len(history) > 180:
        history = history[-180:]
        try:
            with open(hist_path, "w", encoding="utf-8") as f:
                for h in history:
                    f.write(json.dumps(h, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # trend: 当前vs7天前均值
    trend = "STABLE"
    if len(history) >= 42:
        recent_avg = sum(h["score"] for h in history[-6:]) / 6
        old_avg = sum(h["score"] for h in history[-42:-36]) / 6
        diff = recent_avg - old_avg
        if diff > 5:
            trend = "IMPROVING"
        elif diff < -5:
            trend = "DECLINING"
    elif len(history) >= 12:
        recent_avg = sum(h["score"] for h in history[-6:]) / 6
        old_avg = sum(h["score"] for h in history[:6]) / 6
        diff = recent_avg - old_avg
        if diff > 5:
            trend = "IMPROVING"
        elif diff < -5:
            trend = "DECLINING"

    return trend


def _build_system_evo(trade_analysis: dict, tasks: dict, issues: list,
                      scan_plugins: dict, plugin_exec: dict, hours: int,
                      gates: dict, gate_totals: dict) -> dict:
    """S13-S17: 组装system_evo字段。"""
    scores = _calc_system_score(trade_analysis, tasks, issues, scan_plugins, plugin_exec, hours)
    collab_issues = _detect_collaboration_issues(scan_plugins, tasks, issues, gates, gate_totals)
    memory = _parse_evolution_memory()
    trend = _append_evo_history(scores)
    scores["collab_issues"] = collab_issues
    scores["collab_count"] = len(collab_issues)

    return {
        "score": scores["score"],
        "win_rate": scores["win_rate"],
        "errors": scores["errors"],
        "exec_eff": scores["exec_eff"],
        "stability": scores["stability"],
        "baselines": scores["baselines"],
        "trend": trend,
        "collab_issues": collab_issues,
        "collab_count": len(collab_issues),
        "memory_history": memory,
    }


def _build_result(now_str, hours, tasks, summary_metrics,
                  vf_by_plugin, macd_stats, knn_suppress,
                  knn_suppress_total, plugin_exec, governance_actions,
                  bv_stats, gates, gate_totals, issues,
                  vf_by_symbol=None, vf_total=0, scan_plugins=None,
                  vision_filter=None, arbiter=None, macd_div=None,
                  rh_stats=None, l1_stats=None, va_stats=None,
                  trade_analysis=None, pipeline_analysis=None,
                  bv_accuracy=None, fifo_trades=None,
                  block_validation=None, strategy_ranking=None,
                  broker_match=None, plugin_accuracy=None,
                  plugin_phases=None,
                  baseline_data=None,
                  system_evo=None):
    """构建输出数据结构。"""
    # 序列化defaultdict → dict
    _macd = dict(macd_stats)
    _macd["by_symbol"] = {k: dict(v) for k, v in macd_stats.get("by_symbol", {}).items()}
    _vf_plugin = {p: dict(s) for p, s in vf_by_plugin.items()}
    _knn = {p: dict(s) for p, s in knn_suppress.items()}
    _gates = {g: dict(s) for g, s in gates.items()}
    _bv = dict(bv_stats)
    _bv["patterns"] = dict(bv_stats.get("patterns", {}))
    _bv["eval"] = dict(bv_stats.get("eval", {}))
    _bv["by_direction"] = dict(bv_stats.get("by_direction", {}))

    # scan_plugins序列化
    _sp = {}
    for pname, pdata in (scan_plugins or {}).items():
        _sp[pname] = {k: v for k, v in pdata.items() if k not in ("by_symbol", "block_reasons")}
        _sp[pname]["by_symbol"] = {s: dict(d) for s, d in pdata.get("by_symbol", {}).items()}
        _sp[pname]["block_reasons"] = dict(pdata.get("block_reasons", {}))

    # ── ACK: 已确认的问题标记为acked ──
    _ack_path = Path(__file__).parent / "state" / "key009_ack.json"
    _ack_rules = []
    try:
        if _ack_path.exists():
            _ack_data = json.loads(_ack_path.read_text(encoding="utf-8"))
            _now_iso = datetime.now(NY_TZ).isoformat()
            _ack_rules = [a for a in _ack_data.get("acks", [])
                          if a.get("expires", "9999") > _now_iso]
    except Exception:
        pass
    for iss in issues:
        iss["acked"] = False
        iss["fixed"] = False
        iss["fix_note"] = ""
        for rule in _ack_rules:
            if rule.get("task") and rule["task"] != iss.get("task"):
                continue
            if rule.get("type") and rule["type"] != iss.get("type"):
                continue
            # msg子串匹配(可选): 只标记包含指定关键词的issue
            if rule.get("msg_contains") and rule["msg_contains"] not in iss.get("msg", ""):
                continue
            # task匹配(精确或前缀) → 标记acked/fixed
            _status = rule.get("status", "acked")
            if _status == "fixed":
                iss["fixed"] = True
                iss["fix_note"] = rule.get("fix_note", "")
            else:
                iss["acked"] = True
                iss["ack_reason"] = rule.get("reason", "")
            break

    # 历史修复: ack中status=fixed但当前数据没匹配的规则，也作为已修复条目显示
    _matched_fixed = {id(iss) for iss in issues if iss.get("fixed")}
    for rule in _ack_rules:
        if rule.get("status") != "fixed":
            continue
        # 检查是否已匹配过某个issue
        already = any(id(iss) in _matched_fixed for iss in issues
                       if iss.get("task") == rule.get("task"))
        if already:
            continue
        issues.append({
            "task": rule.get("task", ""),
            "type": rule.get("type", "INFO"),
            "msg": f"已修复: {rule.get('fix_note', '')}",
            "fixed": True,
            "fix_note": rule.get("fix_note", ""),
            "acked": False,
            "historical": True,
        })

    return {
        "generated_at": now_str,
        "hours": hours,
        "total_events": sum(t["count"] for t in tasks.values()),
        "total_errors": sum(t["errors"] for t in tasks.values()),
        "tasks": tasks,
        "metrics": summary_metrics,
        "plugins": {
            "vf_total": vf_total,
            "vf_by_plugin": _vf_plugin,
            "vf_by_symbol": vf_by_symbol or {},
            "knn_suppress_total": knn_suppress_total,
            "knn_suppress": _knn,
            "plugin_exec": dict(plugin_exec),
            "governance": governance_actions,
            "scan_plugins": _sp,
        },
        "vision_filter": {
            "total": (vision_filter or {}).get("total", 0),
            "by_symbol": dict((vision_filter or {}).get("by_symbol", {})),
            "by_reason": dict((vision_filter or {}).get("by_reason", {})),
        },
        "macd": _macd,
        "brooks_vision": _bv,
        "gates": {
            "totals": gate_totals,
            "totals_adjusted": {
                **gate_totals,
                "DATA-STALE": gate_totals.get("DATA-STALE-ADJUSTED", gate_totals.get("DATA-STALE", 0)),
            },
            "detail": _gates,
        },
        "arbiter": {
            "total": (arbiter or {}).get("total", 0),
            "by_signal": dict((arbiter or {}).get("by_signal", {})),
            "by_symbol": {s: dict(d) for s, d in (arbiter or {}).get("by_symbol", {}).items()},
            "hold_rate": round((arbiter or {}).get("by_signal", {}).get("HOLD", 0) / max((arbiter or {}).get("total", 0), 1), 3),
        },
        "macd_divergence": {
            "found": (macd_div or {}).get("found", 0),
            "filtered": (macd_div or {}).get("filtered", 0),
            "filter_reasons": dict((macd_div or {}).get("filter_reasons", {})),
            "avg_strength": round(sum((macd_div or {}).get("strengths", [])) / max(len((macd_div or {}).get("strengths", [])), 1), 1),
        },
        "rob_hoffman": {
            "scans": (rh_stats or {}).get("scans", 0),
            "signals": (rh_stats or {}).get("signals", 0),
            "filtered": (rh_stats or {}).get("filtered", 0),
            "er_below_pct": round((rh_stats or {}).get("er_below", 0) / max((rh_stats or {}).get("scans", 0), 1), 3),
            "filter_reasons": dict((rh_stats or {}).get("filter_reasons", {})),
        },
        "l1_diagnosis": {
            "total": (l1_stats or {}).get("total", 0),
            "by_signal": dict((l1_stats or {}).get("by_signal", {})),
        },
        "value_analysis": {
            "fallback": (va_stats or {}).get("fallback", 0),
            "fallback_reasons": dict((va_stats or {}).get("fallback_reasons", {})),
            "batch_total": (va_stats or {}).get("batch_total", 0),
            "batch_failed": (va_stats or {}).get("batch_failed", 0),
        },
        "trade_analysis": trade_analysis or {
            "total": 0, "winners": 0, "losers": 0, "win_rate": 0.0,
            "avg_pnl_pct": 0.0, "total_pnl": 0.0,
            "by_symbol": {}, "by_plugin": {},
            "avg_hold_min": 0.0,
        },
        "pipeline_analysis": pipeline_analysis or [],
        "bv_accuracy": bv_accuracy or {},
        "fifo_trades": fifo_trades or {"total": 0, "winners": 0, "win_rate": 0.0,
                                        "avg_pnl_pct": 0.0, "total_pnl_pct": 0.0,
                                        "by_source": {}, "by_symbol": {}, "by_source_symbol": {}},
        "block_validation": block_validation or {"total_blocked": 0, "validated": 0,
                                                  "correct": 0, "incorrect": 0, "accuracy": 0.0,
                                                  "by_reason": {}, "by_source": {}},
        "strategy_ranking": strategy_ranking or [],
        "broker_match": broker_match or {"enabled": False},
        "broker_pnl": _load_broker_pnl(),
        "options_history": _load_options_history(),
        "plugin_accuracy": plugin_accuracy or {},
        "plugin_phases": plugin_phases or {},
        "baseline": baseline_data or {"stats": {"total": 0, "pass": 0, "block": 0, "no_data": 0, "by_symbol": {}, "by_direction": {}}, "state": {}},
        "system_evo": system_evo or {"score": 0, "baselines": {}, "collab_issues": [], "collab_count": 0, "memory_history": [], "trend": "STABLE"},
        "issues": issues,
    }


def format_text(data: dict) -> str:
    """文本报告。"""
    lines = [
        f"KEY-009 日志审计 | 过去{data['hours']}h | {data['generated_at']}",
        f"总事件: {data['total_events']}  异常: {data['total_errors']}",
        "=" * 60,
    ]
    # GCC任务
    for tid, t in data["tasks"].items():
        icon = {"OK": "+", "ERROR": "!", "SILENT": "?", "LOW": "~"}[t["status"]]
        lines.append(f"[{icon}] {tid}: {t['name']}  events={t['count']} errors={t['errors']}  [{t['status']}]")

    # 外挂
    p = data.get("plugins", {})
    lines.extend(["", "── 外挂运行 ──",
                   f"  VF过滤: {p.get('vf_total', 0)}次  KNN抑制: {p.get('knn_suppress_total', 0)}次",
                   f"  执行: sent={p.get('plugin_exec', {}).get('sent', 0)} skip={p.get('plugin_exec', {}).get('skip', 0)} block={p.get('plugin_exec', {}).get('block', 0)}"])

    # MACD
    md = data.get("macd", {})
    lines.extend(["", "── L2 MACD ──",
                   f"  触发: {md.get('trigger', 0)}  过滤: {md.get('reject', 0)}  执行: {md.get('execute', 0)}  门控拦截: {md.get('gate_block', 0)}"])

    # BV
    bv = data.get("brooks_vision", {})
    ev = bv.get("eval", {})
    lines.extend(["", "── BrooksVision ──",
                   f"  信号: {bv.get('signals', 0)}  执行: {bv.get('executed', 0)}  观察: {bv.get('gate_obs', 0)}",
                   f"  评估: CORRECT={ev.get('CORRECT', 0)} INCORRECT={ev.get('INCORRECT', 0)} NEUTRAL={ev.get('NEUTRAL', 0)}"])

    # 门控
    gt = data.get("gates", {}).get("totals", {})
    if any(v > 0 for v in gt.values()):
        lines.extend(["", "── 门控拦截 ──"])
        for gname, cnt in sorted(gt.items(), key=lambda x: -x[1]):
            if cnt > 0:
                lines.append(f"  {gname}: {cnt}")

    # 交易分析
    ta = data.get("trade_analysis", {})
    if ta.get("total", 0) > 0:
        lines.extend(["", "── 交易分析 ──",
                       f"  总交易: {ta['total']}  胜率: {ta.get('win_rate', 0):.0%}  "
                       f"平均盈利: {ta.get('avg_pnl_pct', 0):+.2f}%",
                       f"  平均持仓: {ta.get('avg_hold_min', 0):.0f}min"])
        by_sym = ta.get("by_symbol", {})
        if by_sym:
            lines.append("  按品种:")
            for s, d in sorted(by_sym.items(), key=lambda x: -x[1].get("total", 0)):
                lines.append(f"    {s}: {d['total']}笔 胜率{d.get('win_rate', 0):.0%} PnL={d.get('total_pnl', 0):+.2f}")
        by_plug = ta.get("by_plugin", {})
        if by_plug:
            lines.append("  按插件:")
            for p, d in sorted(by_plug.items(), key=lambda x: -x[1].get("total", 0)):
                lines.append(f"    {p}: {d['total']}笔 胜率{d.get('win_rate', 0):.0%}")

    # GCC-0197 S5: 外挂信号准确率摘要
    pa = data.get("plugin_accuracy", {})
    if pa:
        lines.extend(["", "── 外挂信号准确率(4H回填) ──"])
        for src in sorted(pa.keys()):
            ov = pa[src].get("_overall", {})
            if ov.get("total", 0) > 0:
                acc_str = f"{ov['acc']:.0%}" if ov.get("acc") is not None else "N/A"
                lines.append(f"  {src}: {acc_str} ({ov['total']}笔decisive, {ov.get('correct',0)}正确)")

    pp = data.get("plugin_phases", {})
    downgraded = [s for s, d in pp.items() if d.get("phase") == "DOWNGRADED"]
    if downgraded:
        lines.append(f"  ⚠ 降级中: {', '.join(downgraded)}")

    # 问题
    if data["issues"]:
        lines.extend(["", "── 问题 & 风险 ──"])
        for iss in data["issues"]:
            lines.append(f"  [{iss['type']}] {iss['task']}: {iss['msg']}")
    return "\n".join(lines)


def export_json(data: dict):
    """导出JSON供dashboard读取。"""
    export = {k: v for k, v in data.items()}
    for t in export.get("tasks", {}).values():
        t.pop("recent", None)
    _write_key009_cache(export, indent=2)


def run_autofix():
    """本地端: 检测autofix.json并调用本地Claude Code修复。
    用法: python key009_audit.py --autofix
    """
    import subprocess
    autofix_path = STATE_DIR / "key009_autofix.json"
    review_path = STATE_DIR / "key009_review_queue.json"

    if not autofix_path.exists():
        print("[KEY009-AUTOFIX] 无待处理任务 (state/key009_autofix.json 不存在)")
        return

    task = json.loads(autofix_path.read_text(encoding="utf-8"))
    if task.get("status") != "PENDING":
        print(f"[KEY009-AUTOFIX] 任务状态={task.get('status')}, 非PENDING, 跳过")
        return

    if not review_path.exists():
        print("[KEY009-AUTOFIX] state/key009_review_queue.json 不存在, 无法分析")
        return

    review_data = json.loads(review_path.read_text(encoding="utf-8"))
    issues = [i for i in review_data.get("issues", []) if i["type"] in ("ERROR", "RISK")]

    # 过滤skip类问题(SignalStack/3Commas/DATA-STALE) — 不给Claude Code修
    SKIP_AUTOFIX = {"GATE-SignalStack", "GATE-3Commas", "DATA-STALE", "GATE-DATA-STALE"}
    issues_to_fix = [i for i in issues if i.get("task", "") not in SKIP_AUTOFIX]
    if not issues_to_fix:
        print(f"[KEY009-AUTOFIX] 所有{len(issues)}个风险均为skip类(SignalStack/DATA-STALE), 跳过autofix")
        task["status"] = "SKIPPED"
        task["finished_at"] = datetime.now(NY_TZ).isoformat()
        autofix_path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
        return

    report = format_text(review_data)

    print(f"[KEY009-AUTOFIX] 发现{len(issues_to_fix)}个可修复问题(跳过{len(issues)-len(issues_to_fix)}个skip类), 启动Claude Code修复...")

    prompt = (
        "你是KEY-009自动修复系统。\n\n"
        f"审计报告:\n{report}\n\n"
        "任务:\n"
        "1. 读取 state/key009_review_queue.json 了解完整审计数据\n"
        "2. 按优先级P0→P1逐个修复(P2可跳过):\n"
        "   - 读取相关源代码找到根因\n"
        "   - 做最小改动修复问题(不重构/不加feature)\n"
        "   - 每修一个问题验证语法正确\n"
        "3. 全部修完后:\n"
        "   - git add 改动的文件\n"
        "   - git commit -m 'fix(KEY-009): 自动复查修复 — [简述改了什么]'\n"
        "重要: 改动必须最小化。只修ERROR和RISK问题。"
    )

    result = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools",
         "Read,Write,Edit,Grep,Glob,Bash", "--max-turns", "30"],
        cwd=str(ROOT),
    )

    # 标记完成
    task["status"] = "DONE" if result.returncode == 0 else "FAILED"
    task["finished_at"] = datetime.now(NY_TZ).isoformat()
    autofix_path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
    print(f"[KEY009-AUTOFIX] 完成, status={task['status']}")

    # 写autofix_result.json — 供server检测后发邮件+写ack
    result_data = {
        "slot": task.get("slot", ""),
        "created_at": task.get("created_at", ""),
        "finished_at": task["finished_at"],
        "status": task["status"],
        "fixed_issues": [{"task": i.get("task", ""), "msg": i.get("msg", "")} for i in issues_to_fix],
        "notified": False,
    }
    result_path = STATE_DIR / "key009_autofix_result.json"
    result_path.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
    print(f"[KEY009-AUTOFIX] autofix_result.json 已写入(status={task['status']}, {len(issues_to_fix)}个问题)")


def main():
    parser = argparse.ArgumentParser(description="KEY-009 日志审计")
    parser.add_argument("--hours", type=int, default=4)
    parser.add_argument("--log", default="logs/server.log,logs/price_scan_engine.log,logs/deepseek_arbiter.log,logs/macd_divergence.log,logs/rob_hoffman_plugin.log,logs/l1_module_diagnosis.log,logs/value_analysis.log")
    parser.add_argument("--json", action="store_true", help="JSON到stdout")
    parser.add_argument("--export", action="store_true", help="写入state/key009_audit.json")
    parser.add_argument("--loop", action="store_true", help="每5分钟循环导出")
    parser.add_argument("--autofix", action="store_true", help="本地端: 检测autofix任务并调用Claude Code修复")
    parser.add_argument("--rule-status", nargs=2, metavar=("RULE_ID", "STATUS"),
                        help="L5: 转换规则状态, e.g. --rule-status KEY-009-R001 ACTIVE")
    args = parser.parse_args()

    if args.rule_status:
        rid, new_st = args.rule_status
        result = rule_transition(rid, new_st)
        if result.get("ok"):
            print(f"✓ {rid}: {result['old_status']} → {new_st}")
        else:
            print(f"✗ {result.get('error', 'unknown error')}")
        return

    if args.autofix:
        run_autofix()
        return

    def _multi_range_export(log_path):
        """生成多时间范围数据(24h/本周/本月)并导出
        时间锚点: 纽约时间 8:00 AM
        - 24h: 今天8am → 明天8am (若当前<8am则用昨天8am)
        - 1w:  本周一8am → 下周一8am
        - 1m:  本月1日8am → 下月1日8am
        """
        now = datetime.now(NY_TZ)
        # ── 24h: 最近一个8am锚点 ──
        today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now < today_8am:
            day_start = today_8am - timedelta(days=1)
        else:
            day_start = today_8am
        # ── 1w: 本周一8am ──
        days_since_monday = now.weekday()  # 0=Mon
        this_monday = now.replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
        if now < this_monday:
            this_monday -= timedelta(weeks=1)
        week_start = this_monday
        # ── 1m: 本月1日8am ──
        month_start = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
        if now < month_start:
            # 退回上月1日8am
            last_month = (now.replace(day=1) - timedelta(days=1))
            month_start = last_month.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
        h_24 = max(int((now - day_start).total_seconds() / 3600), 1)
        h_1w = max(int((now - week_start).total_seconds() / 3600), 1)
        h_1m = max(int((now - month_start).total_seconds() / 3600), 1)
        ranges = {"24h": h_24, "1w": h_1w, "1m": h_1m}
        multi = {}
        def _get_signal_filter_mode():
            # 静态导出版也注入SignalFilter模式，避免dashboard标签缺失
            try:
                _mode_state = ROOT / ".GCC" / "signal_filter" / "mode_state.json"
                if _mode_state.exists():
                    _ms = json.loads(_mode_state.read_text(encoding="utf-8"))
                    _m = str(_ms.get("mode", "")).upper().strip()
                    if _m in ("OBSERVE", "ENFORCE"):
                        return _m
                try:
                    _sdf = importlib.import_module("AIPro.signal_direction_filter")
                except Exception:
                    _sdf = importlib.import_module("signal_direction_filter")
                return "OBSERVE" if getattr(_sdf, "OBSERVE_ONLY", True) else "ENFORCE"
            except Exception:
                return "OFF"

        _sf_mode = _get_signal_filter_mode()
        for label, h in ranges.items():
            multi[label] = audit(log_path, hours=h)
            multi[label]["review_status"] = {
                "phase": "STATIC_EXPORT",
                "slot": "",
                "collect_retries": 0,
                "signal_filter": _sf_mode,
            }
        _write_key009_cache(multi)

        # ── 闭环: 用1w数据写经验卡+生成规则 (避免三范围重复) ──
        week_data = multi.get("1w", {})
        if week_data:
            fifo = week_data.get("fifo_trades", {})
            bv = week_data.get("block_validation", {})
            sr = week_data.get("strategy_ranking", [])
            # 经验卡回写
            cards = _generate_experience_cards(fifo, bv, sr, h_1w)
            saved = _save_cards_to_store(cards)
            if saved:
                print(f"[KEY009] 经验卡写入 {saved}/{len(cards)} 张")
            # 结构化规则
            rules = _extract_rules(sr, bv)
            _save_rules(rules)
            if rules:
                print(f"[KEY009] 规则生成 {len(rules)} 条 → state/key009_rules.json")
            # 注入到multi中供dashboard读取
            multi["1w"]["extracted_rules"] = rules

        # ── 注入 human_guidance (来自 .GCC/human_anchors.json) ──
        _ha_path = ROOT / ".GCC" / "human_anchors.json"
        if _ha_path.exists():
            try:
                _ha_raw = json.loads(_ha_path.read_text(encoding="utf-8"))
                _raw_list = _ha_raw if isinstance(_ha_raw, list) else _ha_raw.get("anchors", [])
                # Separate strategy anchors from direction anchors
                _strategies_raw = [a for a in _raw_list if a.get("type") == "strategy"]
                _anchors_raw = [a for a in _raw_list if a.get("type") != "strategy"]
                _anchors_raw = sorted(_anchors_raw, key=lambda x: x.get("created_at", ""), reverse=True)[:8]
                _dir_map = {"LONG": "bullish", "SHORT": "bearish", "NEUTRAL": "neutral",
                            "BULLISH": "bullish", "BEARISH": "bearish"}
                anchors = [{
                    "anchor_id":    a.get("anchor_id", ""),
                    "symbol":       a.get("key", "") or "全局",
                    "direction":    _dir_map.get((a.get("direction", "NEUTRAL") or "NEUTRAL").upper(), "neutral"),
                    "concern":      a.get("main_concern", a.get("concern", "")),
                    "expires_after": a.get("expires_after", ""),
                    "created_at":   (a.get("created_at", "") or "")[:10],
                } for a in _anchors_raw]
                strategies = [{
                    "anchor_id":  s.get("anchor_id", ""),
                    "name":       s.get("name", ""),
                    "scope":      s.get("scope", ""),
                    "description": s.get("description", ""),
                    "rules":      s.get("rules", {}),
                    "applies_to": s.get("applies_to", []),
                    "timeframe":  s.get("timeframe", ""),
                    "validated":  s.get("validated", False),
                    "validation_note": s.get("validation_note", ""),
                    "created_at": (s.get("created_at", "") or "")[:10],
                    "expires_after": s.get("expires_after", ""),
                    "tracking_status": s.get("tracking_status", ""),
                    "priority":  s.get("priority", "normal"),
                    "main_concern": s.get("main_concern", ""),
                } for s in _strategies_raw]
                multi["human_guidance"] = {
                    "loop_running": False,
                    "loop_last": "",
                    "loop_round": 0,
                    "loop_steps": {},
                    "anchors": anchors,
                    "strategies": strategies,
                }
            except Exception:
                pass
        # ── 注入 8-layer 架构状态 ──
        _gcc_evo_dir = ROOT / ".GCC" / "gcc_evolution"
        _layer_spec = [
            ('L0', 'Foundation\nGovernance', 'L0_setup',        'free'),
            ('L1', 'Memory',                 'L1_memory',        'free'),
            ('L2', 'Retrieval',              'L2_retrieval',     'free'),
            ('L3', 'Distillation',           'L3_distillation',  'free'),
            ('L4', 'Decision',               'L4_decision',      'paid'),
            ('L5', 'Orchestration',          'L5_orchestration', 'paid'),
            ('DA', 'Direction\nAnchor',      'direction_anchor', 'paid'),
        ]
        _layers = []
        for _lid, _lname, _ldir, _ltier in _layer_spec:
            _lpath = _gcc_evo_dir / _ldir
            _py = [f for f in _lpath.glob('*.py') if f.name != '__init__.py'] if _lpath.exists() else []
            _layers.append({'id': _lid, 'name': _lname, 'tier': _ltier, 'active': len(_py) > 0, 'files': len(_py)})
        multi["layers"] = _layers

        # ── 注入 loop_state.json (覆盖 loop_running/loop_last/steps) ──
        _ls_path = ROOT / ".GCC" / "loop_state.json"
        if _ls_path.exists():
            try:
                _ls = json.loads(_ls_path.read_text(encoding="utf-8"))
                if "human_guidance" not in multi:
                    multi["human_guidance"] = {}
                multi["human_guidance"].update({
                    "loop_running": bool(_ls.get("running", False)),
                    "loop_last": _ls.get("last_end", "") or _ls.get("last_start", ""),
                    "loop_round": _ls.get("round", 0),
                    "loop_steps": _ls.get("steps", {}),
                })
            except Exception:
                pass

        _write_key009_cache(multi)

        # ── 生成嵌入数据的 dashboard HTML (可直接 file:// 打开) ──
        _tpl_path = ROOT / "key009_dashboard.html"
        _out_path = STATE_DIR / "key009_dashboard_live.html"
        if _tpl_path.exists():
            try:
                tpl = _tpl_path.read_text(encoding="utf-8")
                inject = f'<script>window.MULTI_DATA = {json.dumps(multi, ensure_ascii=False)};</script>'
                # 在 </head> 前注入
                if '</head>' in tpl:
                    live_html = tpl.replace('</head>', inject + '\n</head>')
                else:
                    live_html = inject + '\n' + tpl
                _out_path.write_text(live_html, encoding="utf-8")
            except Exception as e:
                print(f"[KEY009] 嵌入dashboard生成失败: {e}")

        return multi

    if args.loop:
        print(f"[KEY009-AUDIT] 循环模式启动, 每5分钟刷新 → {EXPORT_FILE}")
        while True:
            multi = _multi_range_export(args.log)
            d24 = multi.get("24h", {})
            print(f"[{datetime.now(NY_TZ).strftime('%H:%M')}] 已刷新: {d24.get('total_events',0)} events, {len(d24.get('issues',[]))} issues")
            time.sleep(300)
    elif args.export:
        _multi_range_export(args.log)
        print(f"Exported multi-range to {EXPORT_FILE.name}")
    elif args.json:
        data = audit(args.log, args.hours)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        data = audit(args.log, args.hours)
        print(format_text(data))


if __name__ == "__main__":
    main()
