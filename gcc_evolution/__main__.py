"""
gcc_evolution/__main__.py
让 `python -m gcc_evolution` 正确转发到 gcc_evo.py

用法（等价）：
    python -m gcc_evolution check
    python -m gcc_evolution ho create
    gcc-evo check
"""
import sys
import os

# 把 .GCC/ 目录加入 sys.path（优先加载本地 gcc_evo.py，而非 pip 安装版本）
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
_gcc_dir = os.path.join(_root, ".GCC")
if os.path.isdir(_gcc_dir):
    sys.path.insert(0, _gcc_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)

# 转发到 gcc_evo.py 的 CLI 入口
try:
    from gcc_evo import cli
    cli()
except ImportError:
    # 降级：直接执行 gcc_evo.py
    import subprocess
    gcc_evo = os.path.join(_gcc_dir, "gcc_evo.py")
    if not os.path.exists(gcc_evo):
        gcc_evo = os.path.join(_root, "gcc_evo.py")
    result = subprocess.run(
        [sys.executable, gcc_evo] + sys.argv[1:],
        cwd=_root
    )
    sys.exit(result.returncode)
