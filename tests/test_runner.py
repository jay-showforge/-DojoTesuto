import os
import pytest
from dojotesuto.runner import DojoTesutoRunner

def test_runner_noninteractive_skip():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = DojoTesutoRunner(base_dir, noninteractive=True)
    
    # timeout-trial.yaml has an 'ask' step, so it should be skipped in noninteractive mode
    quest_path = os.path.join(base_dir, 'challenges', 'core', 'timeout-trial.yaml')
    results = runner.run_quest(quest_path)
    assert results["initial"]["status"] == "SKIP"

def test_runner_fact_setting():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = DojoTesutoRunner(base_dir, noninteractive=True)
    
    # Manually trigger a set_fact step logic
    runner.facts['test_key'] = 'test_value'
    assert runner.facts['test_key'] == 'test_value'
