"""
DojoTesuto Provider: Anthropic Claude

Works with:
  - Claude Haiku, Sonnet, Opus via the Anthropic API

Environment variables:
  ANTHROPIC_API_KEY  — required
  DOJO_MODEL         — model to use (default: claude-haiku-4-5-20251001)

Install: pip install anthropic
"""

import os
import json
from providers import _ANSWER_PROVIDERS, _REFLECT_PROVIDERS
from providers.base import build_answer_system_prompt, build_reflect_messages, parse_reflect_response

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def answer_handler(request: dict) -> str:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    soul = request.get("soul", "")
    attempt = request.get("attempt", "primary")
    quest_id = request.get("quest_id", "")
    question = request["question"]
    facts = request.get("facts", {})
    dojo_contract = request.get("dojo_contract", "")

    system = build_answer_system_prompt(soul, attempt, quest_id, facts, dojo_contract)

    print(f"[Anthropic] {'VARIANT' if attempt == 'variant' else 'Primary'} answer | "
          f"quest={quest_id} | soul_lines={len(soul.splitlines())} | facts={list(facts.keys())} | model={model}")

    resp = _client().messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": question}],
    )
    return resp.content[0].text


def reflect_handler(request: dict) -> dict:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    system_prompt, user_payload = build_reflect_messages(request)

    print(f"[Anthropic] Reflecting | quest={request.get('quest_id')} | model={model}")

    resp = _client().messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt + "\n\nRespond with only a valid JSON object. No markdown fences.",
        messages=[{"role": "user", "content": user_payload}],
    )
    return parse_reflect_response(resp.content[0].text)


# Register
_ANSWER_PROVIDERS["anthropic"] = answer_handler
_REFLECT_PROVIDERS["anthropic"] = reflect_handler

# Alias
_ANSWER_PROVIDERS["claude"] = answer_handler
_REFLECT_PROVIDERS["claude"] = reflect_handler
