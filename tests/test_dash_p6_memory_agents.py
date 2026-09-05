import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[1]

def test_08_llm_agents_no_hardcoded_models():
    page_path = _ROOT / "dashboard" / "pages" / "08_LLM_Agents.py"
    content = page_path.read_text(encoding="utf-8")
    
    # Must find zero literal matches for specific model family names
    assert "gpt-oss" not in content, "Found hardcoded 'gpt-oss' in 08_LLM_Agents.py"
    assert "llama" not in content.lower(), "Found hardcoded 'llama' in 08_LLM_Agents.py"
    assert "qwen" not in content.lower(), "Found hardcoded 'qwen' in 08_LLM_Agents.py"

def test_08_llm_agents_no_forbidden_imports():
    page_path = _ROOT / "dashboard" / "pages" / "08_LLM_Agents.py"
    content = page_path.read_text(encoding="utf-8")
    
    # Must NOT import groq
    assert "import groq" not in content
    assert "from groq" not in content
    
    # Must NOT call build_agents / get_client / .run()
    assert "build_agents" not in content
    assert "get_client" not in content
    assert ".run(" not in content
    assert "run_loop" not in content
    
def test_config_role_tiers_match_requirements():
    sys.path.insert(0, str(_ROOT))
    from src import config
    
    assert "planner" in config.LLM_ROLE_TIER
    assert config.LLM_ROLE_TIER["planner"] == "small"
