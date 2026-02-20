"""
DojoTesuto Provider: OpenAI / OpenAI-compatible APIs

Works with:
  - OpenAI (GPT-4o, GPT-4.1-mini, etc.)
  - Manus (uses OpenAI SDK)
  - Any OpenAI-compatible endpoint (Azure, Together, Groq, etc.)

Environment variables:
  OPENAI_API_KEY       — required
  OPENAI_BASE_URL      — optional, override for compatible endpoints
  DOJO_MODEL           — model to use (default: gpt-4.1-mini)

Install: pip install openai
"""

import os
import json
from providers import _ANSWER_PROVIDERS, _REFLECT_PROVIDERS
from providers.base import build_answer_system_prompt, build_reflect_messages, parse_reflect_response

_DEFAULT_MODEL = "gpt-4.1-mini"


def _client():
    from openai import OpenAI
    kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def answer_handler(request: dict) -> str:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    soul = request.get("soul", "")
    attempt = request.get("attempt", "primary")
    quest_id = request.get("quest_id", "")
    question = request["question"]
    facts = request.get("facts", {})
    dojo_contract = request.get("dojo_contract", "")

    system = build_answer_system_prompt(soul, attempt, quest_id, facts, dojo_contract)

    print(f"[OpenAI] {'VARIANT' if attempt == 'variant' else 'Primary'} answer | "
          f"quest={quest_id} | soul_lines={len(soul.splitlines())} | facts={list(facts.keys())} | model={model}")

    resp = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
    )
    return resp.choices[0].message.content


def reflect_handler(request: dict) -> dict:
    model = os.environ.get("DOJO_MODEL", _DEFAULT_MODEL)
    system_prompt, user_payload = build_reflect_messages(request)

    print(f"[OpenAI] Reflecting | quest={request.get('quest_id')} | model={model}")

    resp = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# Register
_ANSWER_PROVIDERS["openai"] = answer_handler
_REFLECT_PROVIDERS["openai"] = reflect_handler

# Alias: "manus" points here (Manus uses the OpenAI SDK)
_ANSWER_PROVIDERS["manus"] = answer_handler
_REFLECT_PROVIDERS["manus"] = reflect_handler
