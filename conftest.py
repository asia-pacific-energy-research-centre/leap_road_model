"""
Root conftest.py — adds codebase/ to sys.path so pytest can find
adapters, modules, schemas, config without needing package-style imports.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "codebase"))
