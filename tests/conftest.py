"""Pytest root: load repo ``.env`` so env-driven tests see local credentials without exporting."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOTENV = _REPO_ROOT / ".env"
if _DOTENV.is_file():
    load_dotenv(_DOTENV, override=False)
