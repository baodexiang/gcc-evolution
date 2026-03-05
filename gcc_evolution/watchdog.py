"""
GCC v4.7 — Watchdog (Auto-Commit Daemon)
防止因额度耗尽、崩溃或意外退出导致进度丢失。

核心功能：
  1. 后台线程每N分钟自动执行 selfcheck + auto-commit
  2. 检测到dirty文件时自动生成 handoff snapshot
  3. SIGTERM/SIGINT 信号捕获 → 退出前强制flush一次
  4. PID文件管理，防止多实例
  5. 运行日志写入 .gcc/watchdog.log

使用方式：
  gcc-evo watch start          # 启动守护（默认5分钟）
  gcc-evo watch start --interval 3   # 3分钟间隔
  gcc-evo watch stop           # 停止守护
  gcc-evo watch status         # 查看状态
  gcc-evo watch now            # 立即触发一次commit

集成到 gcc_evo.py：
  @cli.command("watch")
  @click.argument("action", type=click.Choice(["start","stop","status","now"]))
  @click.option("--interval", "-i", default=5, help="Commit interval in minutes")
  def cmd_watch(action, interval):
      from gcc_evolution.watchdog import WatchdogCLI
      WatchdogCLI.run(action, interval)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ══════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════

GCC_DIR          = Path(".gcc")
PID_FILE         = GCC_DIR / "watchdog.pid"
STATE_FILE       = GCC_DIR / "watchdog_state.json"
LOG_FILE         = GCC_DIR / "watchdog.log"
MAX_LOG_LINES    = 500      # 超过时截断旧日志
DEFAULT_INTERVAL = 5        # 分钟


# ══════════════════════════════════════════════════════════════
# 日志
# ══════════════════════════════════════════════════════════════

class WatchdogLog:
    def __init__(self, path: Path = LOG_FILE):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, msg: str, level: str = "INFO"):
        line = f"[{_ts()}] [{level}] {msg}\n"
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
            self._trim()
        except Exception as e:
            logger.warning("[WATCHDOG] log write failed: %s", e)
            pass

    def _trim(self):
        """保持日志不超过MAX_LOG_LINES行"""
        try:
            lines = self._path.read_text("utf-8").splitlines(keepends=True)
            if len(lines) > MAX_LOG_LINES:
                self._path.write_text(
                    "".join(lines[-MAX_LOG_LINES:]), encoding="utf-8"
                )
        except Exception as e:
            logger.warning("[WATCHDOG] log trim failed: %s", e)
            pass

    def tail(self, n: int = 20) -> list[str]:
        try:
            lines = self._path.read_text("utf-8").splitlines()
            return lines[-n:]
        except Exception as e:
            logger.warning("[WATCHDOG] log tail read failed: %s", e)
            return []


# ══════════════════════════════════════════════════════════════
# 状态持久化
# ══════════════════════════════════════════════════════════════

class WatchdogState:
    def __init__(self, path: Path = STATE_FILE):
        self._path = path

    def load(self) -> dict:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except Exception as e:
            logger.warning("[WATCHDOG] state load failed: %s", e)
            return {}

    def save(self, data: dict):
        try:
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[WATCHDOG] state save failed: %s", e)
            pass

    def update(self, **kwargs):
        state = self.load()
        state.update(kwargs)
        self.save(state)


# ══════════════════════════════════════════════════════════════
# Git操作（独立于selfcheck，确保可在任意环境运行）
# ══════════════════════════════════════════════════════════════

class GitOps:
    @staticmethod
    def dirty_count() -> int:
        """返回dirty文件数量"""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return 0
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            # 不算 STATUS.md（避免无意义commit）
            lines = [l for l in lines if not l.strip().endswith("STATUS.md")]
            return len(lines)
        except Exception as e:
            logger.warning("[WATCHDOG] git dirty count failed: %s", e)
            return 0

    @staticmethod
    def dirty_files() -> list[str]:
        """返回dirty文件列表"""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return []
            return [l[3:].strip() for l in result.stdout.splitlines() if l.strip()
                    and not l.strip().endswith("STATUS.md")]
        except Exception as e:
            logger.warning("[WATCHDOG] git dirty files failed: %s", e)
            return []

    @staticmethod
    def last_commit_hash() -> str:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception as e:
            logger.warning("[WATCHDOG] git rev-parse failed: %s", e)
            return ""

    @staticmethod
    def commit(message: str) -> bool:
        """Stage all + commit，返回是否成功"""
        try:
            # 确保git user配置
            for cfg in [["git", "config", "user.name", "GCC-Watchdog"],
                        ["git", "config", "user.email", "gcc@local"]]:
                subprocess.run(cfg, capture_output=True, timeout=5)

            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10)
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True, text=True, timeout=15
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("[WATCHDOG] git commit failed: %s", e)
            return False


# ══════════════════════════════════════════════════════════════
# Handoff快照（轻量版，不依赖完整handoff模块）
# ══════════════════════════════════════════════════════════════

class HandoffSnapshot:
    SNAPSHOTS_DIR = GCC_DIR / "handoffs" / "snapshots"

    @classmethod
    def create(cls, dirty_files: list[str], trigger: str = "watchdog") -> Path | None:
        """生成轻量handoff快照，供下一个Agent恢复用"""
        cls.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snap_path = cls.SNAPSHOTS_DIR / f"snap_{ts}.json"

        # 读取当前STATUS.md（如果存在）
        status_content = ""
        status_path = GCC_DIR / "STATUS.md"
        if status_path.exists():
            try:
                status_content = status_path.read_text("utf-8")[:2000]  # 前2000字符
            except Exception as e:
                logger.warning("[WATCHDOG] read STATUS.md failed: %s", e)
                pass

        # 读取当前活跃KEY
        active_keys = cls._get_active_keys()

        # 最近pipeline任务
        active_tasks = cls._get_active_tasks()

        snap = {
            "snapshot_id": f"snap_{ts}",
            "created_at": _now(),
            "trigger": trigger,
            "commit_hash": GitOps.last_commit_hash(),
            "dirty_files_at_snapshot": dirty_files,
            "active_keys": active_keys,
            "active_pipeline_tasks": active_tasks,
            "status_md_excerpt": status_content,
            "recovery_instructions": (
                "RECOVERY: Run `gcc-evo check` then `cat .gcc/STATUS.md` "
                "to restore context. Then run `gcc-evo ho pickup` to continue."
            ),
        }

        try:
            snap_path.write_text(
                json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return snap_path
        except Exception as e:
            logger.warning("[WATCHDOG] snapshot write failed: %s", e)
            return None

    @staticmethod
    def _get_active_keys() -> list[str]:
        try:
            import yaml
            keys_path = GCC_DIR / "keys.yaml"
            if not keys_path.exists():
                return []
            data = yaml.safe_load(keys_path.read_text("utf-8")) or {}
            return [k for k, v in data.items()
                    if isinstance(v, dict) and v.get("status") == "open"]
        except Exception as e:
            logger.warning("[WATCHDOG] get active keys failed: %s", e)
            return []

    @staticmethod
    def _get_active_tasks() -> list[dict]:
        try:
            tasks_path = GCC_DIR / "pipeline" / "tasks.json"
            if not tasks_path.exists():
                return []
            tasks = json.loads(tasks_path.read_text("utf-8"))
            return [
                {"id": t.get("task_id"), "title": t.get("title"), "stage": t.get("stage")}
                for t in tasks
                if t.get("stage") not in ("done", "failed")
            ][:10]
        except Exception as e:
            logger.warning("[WATCHDOG] get active tasks failed: %s", e)
            return []

    @classmethod
    def latest(cls) -> dict | None:
        """读取最新快照"""
        try:
            snaps = sorted(cls.SNAPSHOTS_DIR.glob("snap_*.json"), reverse=True)
            if not snaps:
                return None
            return json.loads(snaps[0].read_text("utf-8"))
        except Exception as e:
            logger.warning("[WATCHDOG] read latest snapshot failed: %s", e)
            return None


# ══════════════════════════════════════════════════════════════
# 核心：单次commit+handoff动作
# ══════════════════════════════════════════════════════════════

def do_commit_cycle(
    log: WatchdogLog,
    state: WatchdogState,
    trigger: str = "scheduled",
    force: bool = False,
) -> dict:
    """
    执行一次完整的commit+handoff循环。
    返回结果摘要dict。
    """
    result = {
        "trigger": trigger,
        "timestamp": _now(),
        "dirty_count": 0,
        "committed": False,
        "snapshot_created": False,
        "selfcheck_ran": False,
        "error": None,
    }

    try:
        dirty_files = GitOps.dirty_files()
        result["dirty_count"] = len(dirty_files)

        # 1. 先尝试运行 gcc-evo check（会生成STATUS.md + auto-commit）
        try:
            check_result = subprocess.run(
                [sys.executable, "-m", "gcc_evolution", "check"],
                capture_output=True, text=True, timeout=30
            )
            # 如果直接调用模块不行，尝试gcc-evo命令
            if check_result.returncode != 0:
                check_result = subprocess.run(
                    ["gcc-evo", "check"],
                    capture_output=True, text=True, timeout=30
                )
            result["selfcheck_ran"] = check_result.returncode == 0
        except Exception as e:
            logger.warning("[WATCHDOG] selfcheck execution failed: %s", e)
            result["selfcheck_ran"] = False

        # 2. 如果selfcheck没有commit成功，手动commit
        if not result["selfcheck_ran"] and (force or dirty_files):
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            trigger_tag = f"[watchdog/{trigger}]"
            msg = f"[GCC] {trigger_tag} auto-save {len(dirty_files)} files ({ts})"
            result["committed"] = GitOps.commit(msg)
            if result["committed"]:
                log.write(f"Committed {len(dirty_files)} files: {', '.join(dirty_files[:5])}")
        elif result["selfcheck_ran"]:
            result["committed"] = True

        # 3. 生成handoff快照（有dirty文件时，或每30分钟强制一次）
        state_data = state.load()
        last_snap_ts = state_data.get("last_snapshot_ts", 0)
        time_since_snap = time.time() - last_snap_ts
        needs_snap = dirty_files or time_since_snap > 1800  # 30分钟

        if needs_snap or force:
            snap_path = HandoffSnapshot.create(dirty_files, trigger=trigger)
            if snap_path:
                result["snapshot_created"] = True
                state.update(last_snapshot_ts=time.time(),
                             last_snapshot_path=str(snap_path))
                log.write(f"Snapshot created: {snap_path.name}")

        # 4. 更新状态
        state.update(
            last_cycle_ts=time.time(),
            last_cycle_at=_now(),
            last_dirty_count=len(dirty_files),
            last_committed=result["committed"],
            total_cycles=state_data.get("total_cycles", 0) + 1,
        )

    except Exception as e:
        result["error"] = str(e)
        log.write(f"Cycle error: {e}", level="ERROR")

    return result


# ══════════════════════════════════════════════════════════════
# 守护线程
# ══════════════════════════════════════════════════════════════

class WatchdogThread(threading.Thread):
    def __init__(self, interval_minutes: int = DEFAULT_INTERVAL):
        super().__init__(daemon=True, name="gcc-watchdog")
        self.interval = interval_minutes * 60  # 转秒
        self.log = WatchdogLog()
        self.state = WatchdogState()
        self._stop_event = threading.Event()
        self._cycle_count = 0

    def run(self):
        self.log.write(f"Watchdog started. Interval: {self.interval//60}min")
        self.state.update(
            started_at=_now(),
            pid=os.getpid(),
            interval_minutes=self.interval // 60,
            status="running",
        )

        # 启动时立即跑一次
        self._run_cycle("startup")

        while not self._stop_event.wait(timeout=self.interval):
            self._run_cycle("scheduled")

        # 退出时最后一次flush
        self._run_cycle("shutdown")
        self.log.write("Watchdog stopped.")
        self.state.update(status="stopped", stopped_at=_now())

    def _run_cycle(self, trigger: str):
        self._cycle_count += 1
        self.log.write(f"Cycle #{self._cycle_count} ({trigger})")
        result = do_commit_cycle(self.log, self.state, trigger=trigger)
        summary = (
            f"dirty={result['dirty_count']} "
            f"committed={result['committed']} "
            f"snapshot={result['snapshot_created']}"
        )
        self.log.write(f"Cycle #{self._cycle_count} done: {summary}")

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════════
# 进程管理（PID文件）
# ══════════════════════════════════════════════════════════════

class WatchdogProcess:
    """管理后台watchdog进程（独立子进程模式）"""

    @staticmethod
    def is_running() -> bool:
        if not PID_FILE.exists():
            return False
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)   # 发送0信号探测进程是否存在
            return True
        except (ProcessLookupError, ValueError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
            return False

    @staticmethod
    def get_pid() -> int | None:
        try:
            return int(PID_FILE.read_text().strip())
        except Exception as e:
            logger.warning("[WATCHDOG] read PID file failed: %s", e)
            return None

    @staticmethod
    def start(interval_minutes: int = DEFAULT_INTERVAL) -> bool:
        """启动独立后台进程"""
        if WatchdogProcess.is_running():
            return False

        # 使用 subprocess 启动独立进程
        script = Path(__file__).resolve()
        cmd = [
            sys.executable, str(script),
            "--daemon", str(interval_minutes)
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,   # 脱离父进程
            )
            PID_FILE.write_text(str(proc.pid))
            time.sleep(0.5)  # 等待进程启动写入state
            return True
        except Exception as e:
            logger.warning("[WATCHDOG] start daemon process failed: %s", e)
            return False

    @staticmethod
    def stop() -> bool:
        """停止后台进程"""
        pid = WatchdogProcess.get_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.warning("[WATCHDOG] stop process (PID %s) failed: %s", pid, e)
            PID_FILE.unlink(missing_ok=True)
            return False


# ══════════════════════════════════════════════════════════════
# CLI接口（供 gcc_evo.py 调用）
# ══════════════════════════════════════════════════════════════

class WatchdogCLI:
    @staticmethod
    def run(action: str, interval: int = DEFAULT_INTERVAL):
        action = action.lower()

        if action == "start":
            WatchdogCLI._start(interval)
        elif action == "stop":
            WatchdogCLI._stop()
        elif action == "status":
            WatchdogCLI._status()
        elif action == "now":
            WatchdogCLI._now()
        elif action == "log":
            WatchdogCLI._log()
        else:
            print(f"Unknown action: {action}. Use: start/stop/status/now/log")

    @staticmethod
    def _start(interval: int):
        GCC_DIR.mkdir(parents=True, exist_ok=True)

        if WatchdogProcess.is_running():
            state = WatchdogState().load()
            print(f"  ⚠ Watchdog already running (PID {WatchdogProcess.get_pid()}, "
                  f"interval {state.get('interval_minutes', '?')}min)")
            return

        ok = WatchdogProcess.start(interval)
        if ok:
            print(f"  ✓ Watchdog started (PID {WatchdogProcess.get_pid()}, "
                  f"interval {interval}min)")
            print(f"    Auto-commit every {interval} minutes.")
            print(f"    Log: {LOG_FILE}")
            print(f"    Stop: gcc-evo watch stop")
        else:
            # 降级：在当前进程用线程模式运行（前台阻塞）
            print(f"  ⚡ Running watchdog in foreground (Ctrl+C to stop)")
            print(f"    Interval: {interval} minutes")
            _run_foreground(interval)

    @staticmethod
    def _stop():
        if not WatchdogProcess.is_running():
            print("  Watchdog is not running.")
            return
        ok = WatchdogProcess.stop()
        if ok:
            print("  ✓ Watchdog stopped.")
        else:
            print("  ✗ Failed to stop watchdog.")

    @staticmethod
    def _status():
        running = WatchdogProcess.is_running()
        state = WatchdogState().load()

        print("\n  ╔══ GCC Watchdog Status ══")
        print(f"  ║  Running:   {'✓ YES' if running else '✗ NO'}")
        if running:
            print(f"  ║  PID:       {WatchdogProcess.get_pid()}")
        if state:
            print(f"  ║  Interval:  {state.get('interval_minutes', '?')} min")
            print(f"  ║  Started:   {state.get('started_at', 'N/A')[:19]}")
            print(f"  ║  Last cycle:{state.get('last_cycle_at', 'N/A')[:19]}")
            print(f"  ║  Total:     {state.get('total_cycles', 0)} cycles")
            print(f"  ║  Last dirty:{state.get('last_dirty_count', 0)} files")

        # 最新快照
        snap = HandoffSnapshot.latest()
        if snap:
            print(f"  ║  Last snap: {snap['snapshot_id']} "
                  f"({snap.get('created_at', '')[:19]})")

        print("  ╚═════════════════════════\n")

        # 最近5条日志
        log = WatchdogLog()
        recent = log.tail(5)
        if recent:
            print("  Recent log:")
            for line in recent:
                print(f"    {line}")
        print()

    @staticmethod
    def _now():
        """立即触发一次commit cycle"""
        print("  ⚡ Running immediate commit cycle...")
        log = WatchdogLog()
        state = WatchdogState()
        result = do_commit_cycle(log, state, trigger="manual", force=True)
        print(f"  ✓ Done:")
        print(f"    Dirty files:  {result['dirty_count']}")
        print(f"    Committed:    {'✓' if result['committed'] else '✗'}")
        print(f"    Snapshot:     {'✓' if result['snapshot_created'] else '✗'}")
        if result.get("error"):
            print(f"    Error: {result['error']}")

    @staticmethod
    def _log():
        """显示最近20条日志"""
        log = WatchdogLog()
        lines = log.tail(20)
        if not lines:
            print("  No watchdog log yet.")
            return
        print(f"\n  ══ Watchdog Log (last {len(lines)} lines) ══")
        for line in lines:
            print(f"  {line}")
        print()


# ══════════════════════════════════════════════════════════════
# 前台模式（降级方案）
# ══════════════════════════════════════════════════════════════

def _run_foreground(interval_minutes: int):
    """前台阻塞运行（subprocess启动失败时的降级方案）"""
    log = WatchdogLog()
    state = WatchdogState()

    # 捕获退出信号
    def _on_signal(signum, frame):
        print("\n  ⚡ Signal received. Running final commit before exit...")
        do_commit_cycle(log, state, trigger="signal_exit", force=True)
        print("  ✓ Final commit done. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    thread = WatchdogThread(interval_minutes)
    thread.start()

    print(f"  Watchdog running. Press Ctrl+C to stop.")
    try:
        while thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        thread.stop()
        thread.join(timeout=10)


# ══════════════════════════════════════════════════════════════
# 守护进程入口（被子进程调用）
# ══════════════════════════════════════════════════════════════

def _daemon_main(interval_minutes: int):
    """独立子进程的主循环"""
    log = WatchdogLog()
    state = WatchdogState()

    # 写入PID
    PID_FILE.write_text(str(os.getpid()))

    # 信号处理
    def _on_term(signum, frame):
        log.write("SIGTERM received. Final flush...", level="WARN")
        do_commit_cycle(log, state, trigger="sigterm", force=True)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    # 主循环
    thread = WatchdogThread(interval_minutes)
    thread.start()
    thread.join()


# ══════════════════════════════════════════════════════════════
# 直接运行入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GCC Watchdog")
    parser.add_argument("--daemon", type=int, metavar="INTERVAL",
                        help="Run as daemon with given interval (minutes)")
    parser.add_argument("action", nargs="?",
                        choices=["start", "stop", "status", "now", "log"],
                        help="CLI action")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL)

    args = parser.parse_args()

    if args.daemon:
        # 被作为子进程调用
        _daemon_main(args.daemon)
    elif args.action:
        WatchdogCLI.run(args.action, args.interval)
    else:
        # 默认：显示状态
        WatchdogCLI.run("status")
