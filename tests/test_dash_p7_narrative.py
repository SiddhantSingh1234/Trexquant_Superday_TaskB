import pytest
from pathlib import Path
from dashboard.lib import data, fixtures
import json

def test_no_run_loop_called():
    loop_page = Path("dashboard/pages/10_The_Loop.py")
    if loop_page.exists():
        content = loop_page.read_text(encoding="utf-8")
        assert "src.loop.run_loop" not in content, "10_The_Loop.py must NEVER call src.loop.run_loop"
        assert ".run_loop(" not in content, "10_The_Loop.py must NEVER call src.loop.run_loop"

def test_alpha_cards_rendering_logic(tmp_path, monkeypatch):
    data.load_cards.clear()
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data, "ARTIFACTS_DIR", tmp_path)
    
    cards = data.load_cards()
    assert len(cards) == 0
    
    data.load_cards.clear()
    fake_card = fixtures.fake_cards(1)[0]
    (cards_dir / "test_card.json").write_text(json.dumps(fake_card), encoding="utf-8")
    
    cards_after = data.load_cards()
    assert len(cards_after) == 1
    
    card = cards_after[0]
    assert "ast_canonical" in card
    assert "formula" in card
    assert "tier1_metrics" in card

