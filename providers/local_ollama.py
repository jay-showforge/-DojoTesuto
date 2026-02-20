"""
DojoTesuto Provider: Local models via Ollama

Works with any model running locally through Ollama (llama3, mistral, gemma, etc.)
No API key required — just a running Ollama instance.

Environment variables:
  OLLAMA_BASE_URL  — Ollama API base (default: http://localhost:11434)
  DOJO_MODEL       — model to use (default: llama3)

Install: pip install ollama
         or just use requests (no extra deps needed)
"""

import os
import json
import re
from providers import _ANSWER_PROVIDERS, _REFLECT_PROVIDERS
from providers.base import build_answer_system_prompt, build_reflect_messages, parse_reflect_response

_DEFAULT_MODEL = "llama3"
_DEFAULT_BASE_URL = "http://localhost:11434"


def _chat(system: str, user: str, model: str, json_mode: bool = False) -> str:
    import urllib.request

    base_url = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/api/chat"

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["format"] = "json"

    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return result["message"]["content"]


def answer_handler(request: dict) -> str:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    soul = request.get("soul", "")
    attempt = request.get("attempt", "primary")
    quest_id = request.get("quest_id", "")
    facts = request.get("facts", {})
    dojo_contract = request.get("dojo_contract", "")

    system = build_answer_system_prompt(soul, attempt, quest_id, facts, dojo_contract)

    print(f"[Ollama] {'VARIANT' if attempt == 'variant' else 'Primary'} answer | "
          f"quest={quest_id} | soul_lines={len(soul.splitlines())} | facts={list(facts.keys())} | model={model}")

    return _chat(system, request["question"], model)


def reflect_handler(request: dict) -> dict:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    system_prompt, user_payload = build_reflect_messages(request)

    print(f"[Ollama] Reflecting | quest={request.get('quest_id')} | model={model}")

    content = _chat(
        system_prompt + "\n\nRespond with only valid JSON. No markdown fences. No preamble.",
        user_payload,
        model,
        json_mode=True,
    )
    return parse_reflect_response(content)


# Register
_ANSWER_PROVIDERS["ollama"] = answer_handler
_REFLECT_PROVIDERS["ollama"] = reflect_handler
_ANSWER_PROVIDERS["local"] = answer_handler
_REFLECT_PROVIDERS["local"] = reflect_handler
