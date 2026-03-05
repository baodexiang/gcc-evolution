"""
GCC v4.0 — LLM Client
Thin abstraction over Anthropic / OpenAI / DeepSeek APIs.
Only needs: generate(system, user) → str
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .config import GCCConfig


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient:
    """
    Minimal LLM client for evaluation and distillation.
    Uses httpx to avoid heavy SDK dependencies.
    """

    def __init__(self, config: GCCConfig):
        self.provider = config.llm_provider
        self.model = config.llm_model
        self.api_key = config.llm_api_key
        self.api_base = config.llm_api_base
        self.temperature = config.llm_temperature

        # Local LLM 模式：不需要 API key
        if self.provider == "local":
            self._local_client = self._init_local(config)
            return

        if not self.api_key:
            raise ValueError(
                f"No API key for {self.provider}. "
                f"Set it in config or env var."
            )
        self._local_client = None

    def _init_local(self, config: GCCConfig):
        """初始化本地 LLM 客户端（可选模块）"""
        try:
            from .local_llm import LocalLLMClient
        except ImportError:
            raise ImportError(
                "本地 LLM 模块未找到。\n"
                "确认 local_llm.py 存在，或安装: pip install gcc-evolution[local]"
            )

        # 可选 fallback 到云端
        fallback = None
        fallback_provider = getattr(config, "llm_fallback_provider", "")
        if fallback_provider:
            import copy
            fallback_config        = copy.copy(config)
            fallback_config.llm_provider = fallback_provider
            try:
                fallback = LLMClient(fallback_config)
            except Exception:
                pass  # fallback 配置失败时不强制要求

        return LocalLLMClient(
            model        = config.llm_model,
            base_url     = config.llm_api_base or "http://localhost:11434",
            fallback_client = fallback,
            temperature  = config.llm_temperature,
            lang_hint    = getattr(config, "llm_lang_hint", "en"),
        )

    def generate(self, system: str, user: str,
                 temperature: float | None = None,
                 max_tokens: int = 2048) -> str:
        """
        Generate a completion. Returns the text content.
        Raises on API errors.
        """
        try:
            import httpx  # noqa: F401
        except ImportError:
            import subprocess, sys
            print("  ⚡ First API call: installing httpx...", flush=True)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "httpx", "--quiet", "--break-system-packages"],
                capture_output=True, text=True)
            if result.returncode == 0:
                print("  ✓ httpx installed successfully", flush=True)
            else:
                raise ImportError(
                    f"httpx install failed. Fix: pip install httpx"
                ) from None

        temp = temperature if temperature is not None else self.temperature

        if self.provider == "local":
            return self._local_client.generate(
                system, user, temperature=temp, max_tokens=max_tokens)
        elif self.provider == "anthropic":
            return self._call_anthropic(system, user, temp, max_tokens)
        else:
            return self._call_openai_compat(system, user, temp, max_tokens)

    def _call_anthropic(self, system: str, user: str,
                        temperature: float, max_tokens: int) -> str:
        import httpx
        url = self.api_base or "https://api.anthropic.com/v1/messages"
        resp = httpx.post(
            url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        # Extract text from content blocks
        return "".join(
            b.get("text", "") for b in data.get("content", [])
            if b.get("type") == "text"
        )

    def _call_openai_compat(self, system: str, user: str,
                            temperature: float, max_tokens: int) -> str:
        """Works with OpenAI, DeepSeek, and any OpenAI-compatible API."""
        import httpx

        if self.provider == "deepseek":
            base = self.api_base or "https://api.deepseek.com/v1"
        elif self.provider == "openai":
            base = self.api_base or "https://api.openai.com/v1"
        else:
            base = self.api_base or "https://api.openai.com/v1"

        url = f"{base.rstrip('/')}/chat/completions"
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class MockLLMClient:
    """For testing without API calls."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.calls: list[dict] = []

    def generate(self, system: str, user: str, **kwargs) -> str:
        self.calls.append({"system": system, "user": user, **kwargs})
        # Return first matching response or default
        for key, val in self.responses.items():
            if key in user:
                return val
        return json.dumps({
            "outcome_score": 0.7,
            "efficiency_score": 0.6,
            "novelty_score": 0.3,
            "key_improvements": ["improved performance"],
            "key_regressions": [],
            "recommendations": ["consider caching"],
        })
