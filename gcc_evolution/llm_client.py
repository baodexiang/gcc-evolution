"""
GCC v4.0 — LLM Client
Thin abstraction over Anthropic / OpenAI / DeepSeek APIs.
Only needs: generate(system, user) → str
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
        self.default_repeat = getattr(config, 'llm_repeat', 1)
        self.debug_prompt = getattr(config, 'llm_debug_prompt', False)

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
            except Exception as e:
                logger.warning("[LLM_CLIENT] fallback LLM config failed: %s", e)

        return LocalLLMClient(
            model        = config.llm_model,
            base_url     = config.llm_api_base or "http://localhost:11434",
            fallback_client = fallback,
            temperature  = config.llm_temperature,
            lang_hint    = getattr(config, "llm_lang_hint", "en"),
        )

    def generate(self, system: str, user: str,
                 temperature: float | None = None,
                 max_tokens: int = 2048,
                 repeat: int = 0) -> str:
        """
        Generate a completion. Returns the text content.
        Raises on API errors.

        GCC-0059: repeat>1 时多次调用LLM，选最长有效JSON响应(降低随机性)。
        GCC-0060: repeat=0 使用config默认值(llm_repeat); debug_prompt打印prompt。
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
        # GCC-0060: repeat=0 → 使用config默认值; >0 → 调用点显式指定
        effective_repeat = repeat if repeat > 0 else self.default_repeat
        effective_repeat = max(1, min(effective_repeat, 5))  # clamp 1~5

        # GCC-0060: debug_prompt模式 — 打印system+user用于调试
        if self.debug_prompt:
            print(f"\n{'='*60}")
            print(f"[DEBUG-PROMPT] model={self.model} temp={temp} repeat={effective_repeat}")
            print(f"[SYSTEM] {system[:200]}{'...' if len(system) > 200 else ''}")
            print(f"[USER] {user[:300]}{'...' if len(user) > 300 else ''}")
            print(f"{'='*60}\n")

        if effective_repeat == 1:
            return self._generate_once(system, user, temp, max_tokens)

        # GCC-0059: 多次调用，选最佳
        candidates: list[str] = []
        for _ in range(effective_repeat):
            try:
                text = self._generate_once(system, user, temp, max_tokens)
                if text:
                    candidates.append(text)
            except Exception as e:
                logger.warning("[LLM_CLIENT] LLM attempt failed: %s", e)
                continue
        if not candidates:
            raise RuntimeError(f"All {effective_repeat} LLM attempts failed")
        return self._select_best(candidates)

    def _generate_once(self, system: str, user: str,
                       temperature: float, max_tokens: int) -> str:
        """GCC-0165: Single LLM call with exponential backoff retry.

        Retries up to 3 times on transient errors (network, 429, 5xx).
        Backoff: 2s → 4s → 8s.
        """
        import httpx
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                if self.provider == "local":
                    return self._local_client.generate(
                        system, user, temperature=temperature, max_tokens=max_tokens)
                elif self.provider == "anthropic":
                    return self._call_anthropic(system, user, temperature, max_tokens)
                else:
                    return self._call_openai_compat(system, user, temperature, max_tokens)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in (429, 500, 502, 503, 529) and attempt < max_retries:
                    wait = 2 ** (attempt + 1)
                    logger.warning("[LLM_CLIENT] HTTP %d, retry %d/%d in %ds",
                                   status, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.ConnectTimeout) as e:
                if attempt < max_retries:
                    wait = 2 ** (attempt + 1)
                    logger.warning("[LLM_CLIENT] network error, retry %d/%d in %ds: %s",
                                   attempt + 1, max_retries, wait, e)
                    time.sleep(wait)
                    continue
                raise

    @staticmethod
    def _select_best(candidates: list[str]) -> str:
        """GCC-0059: 从多次LLM响应中选最佳 — 优先选可解析JSON且最长的。"""
        json_valid = []
        for c in candidates:
            try:
                json.loads(c)
                json_valid.append(c)
            except (json.JSONDecodeError, TypeError):
                # 尝试提取嵌入的JSON对象或数组
                found = False
                for open_ch, close_ch in [("{", "}"), ("[", "]")]:
                    start = c.find(open_ch)
                    end = c.rfind(close_ch) + 1
                    if start >= 0 and end > start:
                        try:
                            json.loads(c[start:end])
                            json_valid.append(c)
                            found = True
                            break
                        except (json.JSONDecodeError, TypeError):
                            pass
                # found not used further, just breaks inner loop
        pool = json_valid if json_valid else candidates
        return max(pool, key=len)

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
