import pytest
import subprocess
import sys
from pathlib import Path
import importlib

def test_pages_importable():
    # Import every pages/*.py and Home.py, assert no import-time exception
    root = Path(__file__).parent.parent
    dashboard_dir = root / "dashboard"
    sys.path.insert(0, str(root))
    
    # Import Home
    try:
        importlib.import_module("dashboard.Home")
    except Exception as e:
        pytest.fail(f"Failed to import dashboard.Home: {e}")
        
    # Import pages
    pages_dir = dashboard_dir / "pages"
    for page_file in pages_dir.glob("*.py"):
        if page_file.name == "__init__.py": continue
        module_name = f"dashboard.pages.{page_file.stem}"
        try:
            importlib.import_module(module_name)
        except Exception as e:
            pytest.fail(f"Failed to import {module_name}: {e}")

def test_build_cache_check():
    # run build_cache.py --check
    root = Path(__file__).parent.parent
    build_cache_path = root / "dashboard" / "build_cache.py"
    result = subprocess.run(
        [sys.executable, str(build_cache_path), "--check"],
        capture_output=True,
        text=True
    )
    # the check should be green according to requirements, though it might report staleness and return non-zero in some cases. We assert returncode == 0
    assert result.returncode == 0, f"build_cache.py --check failed:\n{result.stdout}\n{result.stderr}"
