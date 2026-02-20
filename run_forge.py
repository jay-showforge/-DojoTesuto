#!/usr/bin/env python3
"""
DojoTesuto Universal Forge Runner

Runs the full Forge suite against any agent using provider adapters.

Usage:
  python run_forge.py [suite] [--provider PROVIDER] [--reflect-provider PROVIDER]
                               [--model MODEL] [--save-report]

Examples:
  # Run against OpenAI GPT (default)
  OPENAI_API_KEY=sk-... python run_forge.py core

  # Run against Claude
  ANTHROPIC_API_KEY=sk-ant-... python run_forge.py core --provider anthropic

  # Run against a local Ollama model
  python run_forge.py core --provider ollama --model llama3

  # Use different providers for answering vs reflecting
  OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... \\
    python run_forge.py core --provider openai --reflect-provider anthropic

  # CI/offline test (no API keys needed)
  python run_forge.py core --provider mock

  # Override model
  OPENAI_API_KEY=sk-... python run_forge.py core --provider openai --model gpt-4o

Available providers: openai, anthropic, ollama, mock
Aliases:            manus → openai  |  claude → anthropic  |  local → ollama
"""

import os
import sys
import argparse

# Windows console defaults to cp1252 which cannot encode the emoji used in
# DojoTesuto output (✅ ❌ ⏭️). Reconfigure stdout/stderr to UTF-8 on all
# platforms if the stream supports it (Python 3.7+).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dojotesuto.runner import DojoTesutoRunner
from dojotesuto.forge_budget import ForgeBudget
import providers


def main():
    parser = argparse.ArgumentParser(
        description="DojoTesuto Universal Forge Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("suite", nargs="?", default="core", help="Suite name (default: core)")
    parser.add_argument("--provider", "-p", default=None,
                        help="Answer+reflect provider: openai|anthropic|ollama|mock (default: $DOJO_ANSWER_PROVIDER or openai)")
    parser.add_argument("--reflect-provider", default=None,
                        help="Override reflect provider separately (default: same as --provider)")
    parser.add_argument("--model", "-m", default=None,
                        help="Model override (sets $DOJO_MODEL)")
    parser.add_argument("--save-report", action="store_true",
                        help="Save session report to reports/")
    args = parser.parse_args()

    # Apply env overrides from CLI args
    if args.model:
        os.environ["DOJO_MODEL"] = args.model

    # Load handlers
    try:
        answer_handler = providers.load_answer_handler(args.provider)
        reflect_handler = providers.load_reflect_handler(args.reflect_provider or args.provider)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to load provider: {e}")
        print("   Check that required packages are installed and env vars are set.")
        sys.exit(1)

    base_dir = os.path.abspath(os.path.dirname(__file__))

    budget = ForgeBudget(
        max_reflection_seconds=60,
        max_reflections=10,
        max_suite_seconds=1800,
    )

    runner = DojoTesutoRunner(base_dir=base_dir, forge=True, forge_budget=budget)
    runner.register_answer_handler(answer_handler)
    runner.register_reflection_handler(reflect_handler)

    runner.run_suite(args.suite, save_report_file=args.save_report)


if __name__ == "__main__":
    main()
