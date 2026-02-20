import yaml
import os
import sys

REQUIRED_QUEST_FIELDS = [
    'id', 'tier', 'category', 'description', 
    'mock', 'budget', 'primary', 'variants'
]

# Optional quest fields — validated if present
OPTIONAL_QUEST_FIELDS = ['reflection_hint']

REQUIRED_CHALLENGE_DEF_FIELDS = [
    'steps', 'assertions'
]

VALID_STEP_TYPES = [
    'simulate_timeout', 'inject_text', 'bad_tool_args', 'set_fact', 'ask'
]

VALID_ASSERTION_TYPES = [
    'must_contain', 'must_not_contain', 'must_equal', 'budget_ok'
]

def validate_challenge_definition(challenge_def, quest_id, type_name):
    if not isinstance(challenge_def, dict):
        return False, f"Quest {quest_id}: Invalid {type_name} challenge definition format: expected a dictionary"

    missing = [field for field in REQUIRED_CHALLENGE_DEF_FIELDS if field not in challenge_def]
    if missing:
        return False, f"Quest {quest_id}: {type_name} challenge missing fields: {', '.join(missing)}"
    
    # Validate steps
    for i, step in enumerate(challenge_def.get('steps', [])):
        s_type = step.get('type')
        if s_type not in VALID_STEP_TYPES:
            return False, f"Quest {quest_id}: {type_name} challenge, invalid step type at index {i}: {s_type}"
        
        if s_type == 'bad_tool_args':
            payload = step.get('payload', {})
            if 'tool_name' not in payload:
                return False, f"Quest {quest_id}: {type_name} challenge, step 'bad_tool_args' at index {i} missing 'tool_name'"
    
    # Validate assertions
    for i, assertion in enumerate(challenge_def.get('assertions', [])):
        a_type = assertion.get('type')
        if a_type not in VALID_ASSERTION_TYPES:
            return False, f"Quest {quest_id}: {type_name} challenge, invalid assertion type at index {i}: {a_type}"
        
        if a_type == 'must_equal':
            payload = assertion.get('payload', {})
            if 'value' not in payload:
                return False, f"Quest {quest_id}: {type_name} challenge, assertion 'must_equal' at index {i} missing 'value'"
            if 'key' not in payload and 'field' not in payload:
                return False, f"Quest {quest_id}: {type_name} challenge, assertion 'must_equal' at index {i} requires either 'key' or 'field'"

    return True, "Valid"

def validate_quest(file_path):
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not isinstance(data, dict):
            return False, "Invalid YAML format: expected a dictionary"

        missing = [field for field in REQUIRED_QUEST_FIELDS if field not in data]
        if missing:
            return False, f"Missing quest fields: {', '.join(missing)}"
        
        quest_id = data.get('id', 'unknown')

        # Validate optional reflection_hint
        if 'reflection_hint' in data and not isinstance(data['reflection_hint'], str):
            return False, f"Quest {quest_id}: 'reflection_hint' must be a string"

        # Validate primary challenge
        is_valid, msg = validate_challenge_definition(data.get('primary'), quest_id, 'primary')
        if not is_valid:
            return False, msg

        # Validate variants
        if 'variants' in data:
            if not isinstance(data['variants'], list):
                return False, f"Quest {quest_id}: 'variants' field must be a list"
            for i, variant in enumerate(data['variants']):
                is_valid, msg = validate_challenge_definition(variant, quest_id, f'variant {i}')
                if not is_valid:
                    return False, msg

        return True, "Valid"
    except Exception as e:
        return False, str(e)

def validate_all(challenges_dir):
    print(f"Validating challenges in {challenges_dir}...")
    success = True
    for root, dirs, files in os.walk(challenges_dir):
        for file in files:
            if file.endswith('.yaml') and file != 'index.yaml':
                path = os.path.join(root, file)
                is_valid, msg = validate_quest(path)
                if is_valid:
                    print(f"✅ {file}: {msg}")
                else:
                    print(f"❌ {file}: {msg}")
                    success = False
    return success

if __name__ == "__main__":
    # Windows console defaults to cp1252; reconfigure to UTF-8 so emoji output works.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    challenges_path = os.path.join(base_dir, 'challenges')
    if not validate_all(challenges_path):
        sys.exit(1)
    print("All challenges validated successfully.")
