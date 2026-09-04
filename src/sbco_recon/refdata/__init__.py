"""Reference data recovered from the CASHBOOK_TOOL_for_SBCO workbooks (account
master and clearing pairs from 1.09.6, dashboard order refreshed from 1.09.8)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


def _load(name):
    with open(_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=None)
def account_codes() -> dict:
    """3,006 account codes: hoa, description, side, sign, part."""
    return _load("account_codes.json")


@lru_cache(maxsize=None)
def code_descriptions() -> dict:
    return _load("code_descriptions.json")


@lru_cache(maxsize=None)
def dashboard_codes() -> list:
    """The 428 codes shown on the reconciliation dashboard, in order."""
    return _load("dashboard_codes.json")


@lru_cache(maxsize=None)
def clearing_pairs() -> list:
    """The 8 mismatch/cleared account-code pairs (CBS, PLI/RPLI, IPPB, Other)."""
    return _load("clearing_pairs.json")


def describe(code: str) -> str:
    """Best available description for an account code."""
    entry = account_codes().get(code)
    if entry and entry.get("description"):
        return entry["description"]
    return code_descriptions().get(code, "")


def is_known(code: str) -> bool:
    return code in account_codes() or code in code_descriptions()
