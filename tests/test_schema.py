import os
import pytest
from dojotesuto.validator import validate_quest

def test_core_challenges_schema():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    challenges_dir = os.path.join(base_dir, 'challenges', 'core')
    
    files = [f for f in os.listdir(challenges_dir) if f.endswith('.yaml')]
    assert len(files) > 0, "No challenges found in core directory"
    
    for file in files:
        path = os.path.join(challenges_dir, file)
        is_valid, msg = validate_quest(path)
        assert is_valid, f"Challenge {file} failed validation: {msg}"
