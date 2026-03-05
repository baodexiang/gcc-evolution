"""
GCC v4.91 — Local LLM Support (Optional Module)
可选本地 LLM 模块，气隙/局域网环境下的自我进化支持。

安装方式：
  pip install gcc-evolution[local]   # 包含 Ollama 客户端
  # 或手动：pip install ollama httpx

使用方式（客户按需选择）：
  # .gcc/evolution.yaml
  llm:
    provider: local
    model: llama3.1:8b          # 英文主场景推荐
    base_url: http://localhost:11434
    fallback_provider: openai   # 可选：本地失败时切云端

模型推荐（英文主/中英混合）：
  无 GPU:  llama3.1:8b    (8GB RAM, Q4量化, 英文优先)
  有 GPU:  phi4:14b       (微软,推理强,中英均可)
           llama3.3:70b   (质量最好,需要大内存)

设计原则：
  - 核心引擎代码零改动
  - 客户不安装此模块，GCC 照常使用云端 LLM
  - 只改 config，引擎感知不到差异
  - 英文优先，对中文请求自动提示用英文回答
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 模型推荐表 ────────────────────────────────────────────

RECOMMENDED_MODELS = {
    # 无GPU，CPU only（英文主场景）
    "cpu_primary": {
        "model":   "llama3.1:8b",
        "vendor":  "Meta",
        "ram_gb":  8,
        "gpu":     False,
        "lang":    "en_primary",
        "note":    "最主流，社区最大，合规无顾虑",
    },
    # 无GPU，中英混合
    "cpu_bilingual": {
        "model":   "phi4:14b",
        "vendor":  "Microsoft",
        "ram_gb":  16,
        "gpu":     False,
        "note":    "微软出品，推理强，中英均可",
    },
    # 有GPU，推荐
    "gpu_recommended": {
        "model":   "phi4:14b",
        "vendor":  "Microsoft",
        "ram_gb":  10,
        "gpu":     True,
        "vram_gb": 10,
        "note":    "性价比最高，推理质量好",
    },
    # 有GPU，最高质量
    "gpu_best": {
        "model":   "llama3.3:70b",
        "vendor":  "Meta",
        "ram_gb":  48,
        "gpu":     True,
        "vram_gb": 40,
        "note":    "质量接近云端，需要高端工作站",
    },
}

# GCC 任务对模型能力的最低要求
TASK_MODEL_MAP = {
    "log_classify":    "3b",   # 日志分类/关键词提取
    "suggest":         "7b",   # 建议生成
    "opinion":         "14b",  # 多维度判断（推荐14B+）
    "retrospective":   "30b",  # 复杂回溯分析（建议云端）
}


# ── 本地 LLM 客户端 ───────────────────────────────────────

class LocalLLMClient:
    """
    本地 LLM 客户端，兼容 GCC LLMClient 接口。
    通过 Ollama 调用本地模型，API 格式与 OpenAI 兼容。

    客户不安装此模块时，GCC 正常使用云端 LLM。
    """

    def __init__(self,
                 model: str = "llama3.1:8b",
                 base_url: str = "http://localhost:11434",
                 fallback_client=None,
                 temperature: float = 0.3,
                 lang_hint: str = "en"):
        self.model           = model
        self.base_url        = base_url.rstrip("/")
        self.fallback_client = fallback_client  # 失败时切云端
        self.temperature     = temperature
        self.lang_hint       = lang_hint        # en / zh / auto
        self._health_cache   = None
        self._health_ts      = 0.0

    def generate(self, system: str, user: str,
                 temperature: float | None = None,
                 max_tokens: int = 2048) -> str:
        """
        兼容 LLMClient.generate() 接口。
        优先本地模型，失败时 fallback 到云端。
        """
        # 英文优先：在 system prompt 末尾加语言指令
        system = self._apply_lang_hint(system)

        temp = temperature if temperature is not None else self.temperature

        try:
            if not self.is_healthy():
                raise ConnectionError("Ollama 服务未就绪")
            return self._call_ollama(system, user, temp, max_tokens)
        except Exception as e:
            if self.fallback_client:
                # 静默 fallback 到云端
                return self.fallback_client.generate(
                    system, user, temperature=temperature, max_tokens=max_tokens)
            raise RuntimeError(
                f"本地 LLM 调用失败且无 fallback: {e}\n"
                f"检查 Ollama 是否运行: ollama serve\n"
                f"模型是否已下载: ollama pull {self.model}"
            ) from e

    def _call_ollama(self, system: str, user: str,
                     temperature: float, max_tokens: int) -> str:
        """调用 Ollama OpenAI 兼容接口"""
        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": temperature,
            "max_tokens":  max_tokens,
            "stream":      False,
        }

        resp = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=120.0,   # 本地模型推理可能较慢
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _apply_lang_hint(self, system: str) -> str:
        """根据语言设置在 system prompt 末尾加语言指令"""
        if self.lang_hint == "en":
            return system + "\n\nRespond in English only."
        elif self.lang_hint == "zh":
            return system + "\n\n请用中文回答。"
        # auto: 不干预
        return system

    # ── 健康检查 ──────────────────────────────────────────

    def is_healthy(self, cache_seconds: int = 30) -> bool:
        """检查 Ollama 是否在线（带缓存，避免每次调用都检查）"""
        import time
        now = time.time()
        if self._health_cache is not None and (now - self._health_ts) < cache_seconds:
            return self._health_cache

        try:
            import httpx
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            self._health_cache = resp.status_code == 200
        except Exception as e:
            logger.warning("[LOCAL_LLM] health check failed: %s", e)
            self._health_cache = False

        self._health_ts = now
        return self._health_cache

    def list_local_models(self) -> list[str]:
        """列出 Ollama 已下载的模型"""
        try:
            import httpx
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception as e:
            logger.warning("[LOCAL_LLM] list models failed: %s", e)
            return []

    def pull_model(self, model: str | None = None) -> bool:
        """
        下载模型到本地（需要联网，一次性操作）。
        下载后断网，模型永久可用。
        """
        target = model or self.model
        import subprocess, sys
        print(f"  下载模型 {target}（需要联网，仅需一次）...")
        result = subprocess.run(
            ["ollama", "pull", target],
            capture_output=False,
        )
        return result.returncode == 0

    def model_info(self) -> dict:
        """获取当前模型信息"""
        rec = RECOMMENDED_MODELS
        # 匹配推荐表
        for key, info in rec.items():
            if info["model"] in self.model:
                return info
        return {"model": self.model, "note": "自定义模型"}

    # ── 任务能力评估 ──────────────────────────────────────

    def capability_check(self) -> dict:
        """
        评估当前本地模型对 GCC 各任务的能力。
        帮助客户了解哪些功能可以离线运行，哪些需要云端。
        """
        # 从模型名称推断大小
        size = self._parse_model_size()

        results = {}
        for task, min_size in TASK_MODEL_MAP.items():
            min_b = int(min_size.replace("b", ""))
            results[task] = {
                "supported": size >= min_b,
                "quality":   "good" if size >= min_b * 2 else
                             "ok"   if size >= min_b else "poor",
            }

        return {
            "model":      self.model,
            "size_b":     size,
            "lang_hint":  self.lang_hint,
            "tasks":      results,
            "suggestion": self._capability_suggestion(size),
        }

    def _parse_model_size(self) -> int:
        """从模型名称解析参数量（B）"""
        import re
        m = re.search(r"(\d+)b", self.model.lower())
        return int(m.group(1)) if m else 7  # 默认假设 7B

    def _capability_suggestion(self, size: int) -> str:
        if size >= 30:
            return "可离线运行全部 GCC 功能，质量接近云端"
        elif size >= 14:
            return "可离线运行大部分功能，复杂 retrospective 建议联网"
        elif size >= 7:
            return "可离线运行 suggest/opinion，质量有所下降"
        else:
            return "只适合简单分类任务，建议升级到 7B+"


# ── 安装助手 ──────────────────────────────────────────────

class LocalLLMSetup:
    """
    引导客户安装和配置本地 LLM。
    gcc-evo local setup 命令调用此类。
    """

    @staticmethod
    def detect_hardware() -> dict:
        """检测硬件配置"""
        import platform, subprocess

        info = {
            "os":      platform.system(),
            "arch":    platform.machine(),
            "ram_gb":  0,
            "gpu":     False,
            "gpu_vram_gb": 0,
        }

        # RAM
        try:
            import psutil
            info["ram_gb"] = round(psutil.virtual_memory().total / 1e9)
        except ImportError:
            pass

        # GPU（NVIDIA）
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                vram = int(result.stdout.strip().split("\n")[0]) // 1024
                info["gpu"]          = True
                info["gpu_vram_gb"]  = vram
        except Exception as e:
            logger.warning("[LOCAL_LLM] detect gpu failed: %s", e)

        return info

    @staticmethod
    def recommend_model(hardware: dict) -> dict:
        """根据硬件推荐模型"""
        ram   = hardware.get("ram_gb", 8)
        gpu   = hardware.get("gpu", False)
        vram  = hardware.get("gpu_vram_gb", 0)

        if gpu and vram >= 40:
            return RECOMMENDED_MODELS["gpu_best"]
        elif gpu and vram >= 10:
            return RECOMMENDED_MODELS["gpu_recommended"]
        elif ram >= 16:
            return RECOMMENDED_MODELS["cpu_bilingual"]
        else:
            return RECOMMENDED_MODELS["cpu_primary"]

    @staticmethod
    def check_ollama_installed() -> bool:
        """检查 Ollama 是否已安装"""
        import subprocess
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def generate_config(model: str,
                        base_url: str = "http://localhost:11434",
                        fallback: str = "") -> str:
        """生成 evolution.yaml 的 llm 配置片段"""
        lines = [
            "llm:",
            f"  provider: local",
            f"  model: {model}",
            f"  base_url: {base_url}",
            f"  temperature: 0.3",
            f"  lang_hint: en    # en / zh / auto",
        ]
        if fallback:
            lines += [
                f"  # 本地失败时自动切换到云端（可选）",
                f"  fallback_provider: {fallback}",
            ]
        return "\n".join(lines)
