"""
DojoTesuto Provider Adapters

Each provider module exposes two callables:
  answer_handler(request: dict) -> str
  reflect_handler(request: dict) -> dict

Select a provider at runtime via environment variables:
  DOJO_ANSWER_PROVIDER   — which provider to use for quest answers
  DOJO_REFLECT_PROVIDER  — which provider to use for forge reflection
  DOJO_MODEL             — override the default model for the selected provider

Usage:
  from providers import load_answer_handler, load_reflect_handler
  runner.register_answer_handler(load_answer_handler())
  runner.register_reflection_handler(load_reflect_handler())
"""

import os

_ANSWER_PROVIDERS = {}
_REFLECT_PROVIDERS = {}


def register(name):
    """Decorator to register a provider module by name."""
    def decorator(cls):
        _ANSWER_PROVIDERS[name] = cls.answer_handler
        _REFLECT_PROVIDERS[name] = cls.reflect_handler
        return cls
    return decorator


def load_answer_handler(provider_name=None):
    name = provider_name or os.environ.get("DOJO_ANSWER_PROVIDER", "openai")
    _ensure_loaded(name)
    if name not in _ANSWER_PROVIDERS:
        raise ValueError(f"Unknown answer provider: '{name}'. Available: {list(_ANSWER_PROVIDERS)}")
    return _ANSWER_PROVIDERS[name]


def load_reflect_handler(provider_name=None):
    name = provider_name or os.environ.get("DOJO_REFLECT_PROVIDER", os.environ.get("DOJO_ANSWER_PROVIDER", "openai"))
    _ensure_loaded(name)
    if name not in _REFLECT_PROVIDERS:
        raise ValueError(f"Unknown reflect provider: '{name}'. Available: {list(_REFLECT_PROVIDERS)}")
    return _REFLECT_PROVIDERS[name]


def _ensure_loaded(name):
    """Lazy-import the provider module so unused providers don't require their deps."""
    if name in _ANSWER_PROVIDERS:
        return
    try:
        import importlib
        importlib.import_module(f"providers.{name}")
    except ModuleNotFoundError:
        pass  # will be caught by caller
