import json
import os
from analytics_engine import analyze_repo_data

TEST_FILE_PATH = "test_story.json"


def test_analyze_repo_data_from_file():
    assert os.path.exists(TEST_FILE_PATH), f"Please create {TEST_FILE_PATH} first!"

    with open(TEST_FILE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    results = analyze_repo_data(raw_data)
    assert isinstance(results, list)

    if len(results) > 0:
        first_commit = results[0]
        assert "confidence_score" in first_commit
        assert "hash" in first_commit
        assert 0.0 <= first_commit["confidence_score"] <= 1.0


def test_confidence_scoring_logic_specifically():
    fake_json_data = {
        "timeline": [
            {
                "hash": "123",
                "author": "Alice",
                "message": "fix: updated login bug",
                "files_changed": ["main.py"]
            }
        ]
    }

    results = analyze_repo_data(fake_json_data)
    assert results[0]["confidence_score"] == 1.0
