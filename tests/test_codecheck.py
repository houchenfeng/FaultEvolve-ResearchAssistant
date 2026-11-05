"""Tests for code validation utilities."""

import pytest

from faultevolve.common.codecheck import (
    extract_code_from_response,
    extract_hypothesis_from_response,
    extract_intent_from_response,
    full_check,
    pattern_check,
    syntax_check,
)


def test_syntax_check_valid():
    """Test syntax check with valid Python."""
    code = """
def main():
    print("Hello, world!")

if __name__ == "__main__":
    main()
"""
    assert syntax_check(code) == ""


def test_syntax_check_invalid():
    """Test syntax check with invalid Python."""
    code = "def main( :"
    result = syntax_check(code)
    assert "syntax error" in result


def test_pattern_check_clean():
    """Test pattern check with clean code."""
    code = """
import pandas as pd
import os

data_dir = args.data_dir
train = pd.read_csv(os.path.join(data_dir, 'train.csv'))
"""
    assert pattern_check(code) == ""


def test_pattern_check_detects_path_climbing():
    """Test pattern check detects path climbing."""
    code = "path = data_dir + '/../secret'"
    result = pattern_check(code)
    assert "path climbing" in result


def test_pattern_check_detects_parent():
    """Test pattern check detects .parent."""
    code = "p = Path(args.data_dir).parent"
    result = pattern_check(code)
    assert "path climbing" in result


def test_pattern_check_detects_glob():
    """Test pattern check detects glob."""
    code = "files = glob.glob('*.csv')"
    result = pattern_check(code)
    assert "directory listing" in result


def test_pattern_check_detects_listdir():
    """Test pattern check detects listdir."""
    code = "files = os.listdir(data_dir)"
    result = pattern_check(code)
    assert "directory listing" in result


def test_pattern_check_detects_subprocess():
    """Test pattern check detects subprocess."""
    code = "import subprocess"
    result = pattern_check(code)
    assert "process/network escape" in result


def test_pattern_check_detects_getcwd():
    """Test pattern check detects getcwd."""
    code = "cwd = os.getcwd()"
    result = pattern_check(code)
    assert "working-directory access" in result


def test_pattern_check_detects_holdout():
    """Test pattern check detects holdout path."""
    code = "pd.read_csv('data/holdout/test.csv')"
    result = pattern_check(code)
    assert "evaluator-only path" in result


def test_pattern_check_ignores_comments():
    """Test pattern check ignores patterns in comments."""
    code = "# This uses glob for matching  \nx = 1"
    assert pattern_check(code) == ""


def test_full_check_valid():
    """Test full check with valid code."""
    code = """
import os
import pandas as pd

def main():
    data = pd.read_csv('train.csv')
    return data

if __name__ == "__main__":
    main()
"""
    assert full_check(code) == ""


def test_full_check_syntax_error():
    """Test full check catches syntax errors."""
    code = "def main(:"
    result = full_check(code)
    assert "syntax error" in result


def test_full_check_pattern_violation():
    """Test full check catches pattern violations."""
    code = """
import subprocess
def main():
    subprocess.run(['ls'])
"""
    result = full_check(code)
    assert "process/network escape" in result


def test_extract_code_from_response():
    """Test extracting code from LLM response."""
    response = """Here's the improved code:

```python
def main():
    print("Hello")
```

This code prints hello.
"""
    code = extract_code_from_response(response)
    assert code is not None
    assert "def main():" in code


def test_extract_code_no_block():
    """Test extracting code when no code block."""
    response = "Here is some text without code."
    assert extract_code_from_response(response) is None


def test_extract_intent_from_response():
    """Test extracting intent from response."""
    response = """
<intent>Add vendor-specific features</intent>

```python
# code here
```
"""
    intent = extract_intent_from_response(response)
    assert intent == "Add vendor-specific features"


def test_extract_intent_missing():
    """Test extracting intent when not present."""
    response = "No intent tags here"
    assert extract_intent_from_response(response) == ""


def test_extract_hypothesis_from_response():
    """Test extracting hypothesis from response."""
    response = """
<hypothesis>Using trend features will improve recall</hypothesis>
<intent>Add 7-day trend features</intent>

```python
# code
```
"""
    hypothesis = extract_hypothesis_from_response(response)
    assert "trend features" in hypothesis
