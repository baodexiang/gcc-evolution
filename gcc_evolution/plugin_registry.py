"""
GCC v4.90 — Plugin Registry
插件统一注册管理，第三方可以通过标准接口接入引擎。

设计原则：
  引擎核心不变，业务逻辑通过插件注册接入。
  支持三类插件：
    Advisor     — 外部建议器（Vision、模型、规则引擎）
    Filter      — 执行前过滤器
    Validator   — 回溯验证器

使用方式：
  # 注册
  registry = PluginRegistry()
  registry.register_advisor("vision", MyVisionAdvisor())
  registry.register_filter("anchor_filter", MyAnchorFilter())

  # 使用
  advisor = registry.get_advisor("vision")
  chain   = registry.build_filter_chain()

  # 通过配置文件注册（推荐）
  # .gcc/plugins.yaml:
  #   advisors:
  #     - name: vision
  #       class: myproject.VisionAdvisor
  #       config: {model: gpt-4o}
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class PluginMeta:
    """插件元数据"""
    name:        str
    plugin_type: str        # advisor / filter / validator
    class_path:  str        # 如 myproject.VisionAdvisor
    config:      dict = field(default_factory=dict)
    enabled:     bool = True
    description: str = ""
    version:     str = "1.0.0"


class PluginRegistry:
    """
    插件注册表，管理所有 Advisor / Filter / Validator。

    两种注册方式：
      1. 代码注册：registry.register_advisor("name", instance)
      2. 配置文件：registry.load_from_config(".gcc/plugins.yaml")
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir = Path(gcc_dir)
        self._advisors:   dict[str, Any] = {}
        self._filters:    dict[str, Any] = {}
        self._validators: dict[str, Any] = {}
        self._meta:       dict[str, PluginMeta] = {}

    # ── 注册 ──────────────────────────────────────────────────

    def register_advisor(self, name: str, instance,
                         description: str = "", version: str = "1.0.0"):
        """注册外部建议器"""
        from gcc_evolution.advisor import ExternalAdvisor
        if not isinstance(instance, ExternalAdvisor):
            raise TypeError(f"{name} 必须继承 ExternalAdvisor")
        self._advisors[name] = instance
        self._meta[name] = PluginMeta(
            name=name, plugin_type="advisor",
            class_path=f"{type(instance).__module__}.{type(instance).__name__}",
            description=description, version=version,
        )

    def register_filter(self, name: str, instance,
                        description: str = "", version: str = "1.0.0"):
        """注册执行前过滤器"""
        from gcc_evolution.pre_filter import PreExecutionFilter
        if not isinstance(instance, PreExecutionFilter):
            raise TypeError(f"{name} 必须继承 PreExecutionFilter")
        self._filters[name] = instance
        self._meta[name] = PluginMeta(
            name=name, plugin_type="filter",
            class_path=f"{type(instance).__module__}.{type(instance).__name__}",
            description=description, version=version,
        )

    def register_validator(self, name: str, instance,
                           description: str = "", version: str = "1.0.0"):
        """注册回溯验证器"""
        self._validators[name] = instance
        self._meta[name] = PluginMeta(
            name=name, plugin_type="validator",
            class_path=f"{type(instance).__module__}.{type(instance).__name__}",
            description=description, version=version,
        )

    # ── 获取 ──────────────────────────────────────────────────

    def get_advisor(self, name: str = None):
        """获取建议器，name 为空时返回第一个"""
        if not self._advisors:
            return None
        if name:
            return self._advisors.get(name)
        return next(iter(self._advisors.values()))

    def get_filter(self, name: str):
        return self._filters.get(name)

    def get_validator(self, name: str = None):
        if not self._validators:
            return None
        if name:
            return self._validators.get(name)
        return next(iter(self._validators.values()))

    def build_filter_chain(self, names: list[str] = None):
        """
        构建过滤器链。
        names 为空时使用所有已注册的过滤器。
        """
        from gcc_evolution.pre_filter import FilterChain
        if names:
            filters = [self._filters[n] for n in names if n in self._filters]
        else:
            filters = list(self._filters.values())
        return FilterChain(filters)

    # ── 配置文件加载 ──────────────────────────────────────────

    def load_from_config(self, config_path: str | Path = None) -> int:
        """
        从配置文件加载插件。

        plugins.yaml 格式：
          advisors:
            - name: vision
              class: myproject.VisionAdvisor
              config:
                model: gpt-4o
                endpoint: https://...
              description: Vision 图像分析建议器

          filters:
            - name: anchor_filter
              class: myproject.AnchorFilter
              enabled: true

          validators:
            - name: vision_validator
              class: myproject.VisionValidator
        """
        path = Path(config_path or self.gcc_dir / "plugins.yaml")
        if not path.exists():
            return 0

        if HAS_YAML:
            data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            return 0

        loaded = 0
        for plugin_type, register_fn in [
            ("advisors",   self._load_advisor),
            ("filters",    self._load_filter),
            ("validators", self._load_validator),
        ]:
            for entry in data.get(plugin_type, []):
                if not entry.get("enabled", True):
                    continue
                try:
                    register_fn(entry)
                    loaded += 1
                except Exception as e:
                    print(f"  ⚠ 插件加载失败 [{entry.get('name')}]: {e}")

        return loaded

    def save_config(self, config_path: str | Path = None):
        """把当前注册的插件保存为配置文件"""
        if not HAS_YAML:
            return
        path = Path(config_path or self.gcc_dir / "plugins.yaml")
        data: dict = {"advisors": [], "filters": [], "validators": []}
        for name, meta in self._meta.items():
            entry = {
                "name":        meta.name,
                "class":       meta.class_path,
                "enabled":     meta.enabled,
                "description": meta.description,
                "version":     meta.version,
            }
            if meta.config:
                entry["config"] = meta.config
            data[f"{meta.plugin_type}s"].append(entry)
        path.write_text(_yaml.dump(data, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")

    # ── 查询 ──────────────────────────────────────────────────

    def list_all(self) -> list[PluginMeta]:
        return list(self._meta.values())

    def status(self) -> dict:
        return {
            "advisors":   list(self._advisors.keys()),
            "filters":    list(self._filters.keys()),
            "validators": list(self._validators.keys()),
            "total":      len(self._meta),
        }

    def is_empty(self) -> bool:
        return len(self._meta) == 0

    # ── 内部 ──────────────────────────────────────────────────

    def _load_class(self, class_path: str, config: dict):
        """动态加载类并实例化"""
        module_path, class_name = class_path.rsplit(".", 1)
        module   = importlib.import_module(module_path)
        cls      = getattr(module, class_name)
        return cls(**config) if config else cls()

    def _load_advisor(self, entry: dict):
        instance = self._load_class(entry["class"], entry.get("config", {}))
        self.register_advisor(
            entry["name"], instance,
            description=entry.get("description", ""),
            version=entry.get("version", "1.0.0"),
        )

    def _load_filter(self, entry: dict):
        instance = self._load_class(entry["class"], entry.get("config", {}))
        self.register_filter(
            entry["name"], instance,
            description=entry.get("description", ""),
        )

    def _load_validator(self, entry: dict):
        instance = self._load_class(entry["class"], entry.get("config", {}))
        self.register_validator(
            entry["name"], instance,
            description=entry.get("description", ""),
        )


# ── 全局单例（可选使用）────────────────────────────────────────

_global_registry: PluginRegistry | None = None


def get_registry(gcc_dir: str | Path = ".gcc") -> PluginRegistry:
    """获取全局插件注册表（单例）"""
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry(gcc_dir)
        # 自动加载配置文件
        _global_registry.load_from_config()
    return _global_registry


def reset_registry():
    """重置全局注册表（测试用）"""
    global _global_registry
    _global_registry = None
