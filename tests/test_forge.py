import os
import json
import pytest
from dojotesuto.runner import DojoTesutoRunner

def test_forge_sandboxing(tmp_path):
    base_dir = tmp_path
    (base_dir / "challenges").mkdir()
    (base_dir / "challenges" / "core").mkdir()

    runner = DojoTesutoRunner(str(base_dir), forge=True)

    reflection_data = {
        "failure_reason": "test",
        "guardrail_patch": "test patch",
        "skill_patch": {
            "create_files": [
                {"path": "SOUL.md", "content": "safe"},
                {"path": "../outside.txt", "content": "malicious"}
            ]
        }
    }

    runner.apply_patch("test-quest", reflection_data, "response", [])

    assert os.path.exists(os.path.join(base_dir, "SOUL.md"))
    assert not os.path.exists(os.path.join(base_dir, "../outside.txt"))

def test_forge_patch_records(tmp_path):
    base_dir = tmp_path
    (base_dir / "challenges").mkdir()
    runner = DojoTesutoRunner(str(base_dir), forge=True)

    reflection_data = {
        "failure_reason": "logic error",
        "guardrail_patch": "always verify tool args",
        "confidence": 0.9,
        "skill_patch": {}
    }

    runner.apply_patch("test-quest", reflection_data, "response", [{"type": "must_contain"}])

    patches = os.listdir(os.path.join(base_dir, "patches"))
    assert len(patches) == 1
    assert patches[0].startswith("test-quest-")

def test_forge_reflection_handler(tmp_path):
    base_dir = tmp_path
    (base_dir / "challenges").mkdir()
    runner = DojoTesutoRunner(str(base_dir), forge=True)

    # Confirm no handler = not configured
    assert not runner.reflection_engine.is_configured()

    # Register a mock handler
    def mock_handler(request):
        return {
            "failure_reason": "mock failure",
            "guardrail_patch": "mock guardrail",
            "skill_patch": {},
            "confidence": 1.0
        }

    runner.register_reflection_handler(mock_handler)
    assert runner.reflection_engine.is_configured()

def test_forge_reflection_request_shape(tmp_path):
    base_dir = tmp_path
    (base_dir / "challenges").mkdir()
    runner = DojoTesutoRunner(str(base_dir), forge=True)

    engine = runner.reflection_engine
    request = engine.build_request(
        quest_data={"id": "test-quest", "description": "test"},
        failed_assertions=[{"type": "must_contain"}],
        agent_response="bad response",
        current_soul="",
        dojo_prompt_content="dojo text"
    )

    assert request["quest_id"] == "test-quest"
    assert request["agent_response"] == "bad response"
    assert "_system_prompt" in request
    assert "_schemas" in request
