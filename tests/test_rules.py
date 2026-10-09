"""Valida rules/*.toml: estructura correcta y que cada 'example' coincide con su 'match'."""
import re
import tomllib
from pathlib import Path

import pytest

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
REQUIRED = {"id", "stack", "match", "cause", "fix"}


def _rules():
    out = []
    for f in sorted(RULES_DIR.glob("*.toml")):
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        out += [(f.name, r) for r in data.get("rule", [])]
    return out


def test_rules_exist():
    assert _rules()


def test_ids_unique():
    ids = [r["id"] for _, r in _rules()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("fname,rule", _rules(), ids=lambda x: x["id"] if isinstance(x, dict) else x)
def test_rule_valid(fname, rule):
    assert REQUIRED <= set(rule), f"{fname}: faltan campos en {rule.get('id')}"
    rx = re.compile(rule["match"])
    if "example" in rule:
        assert rx.search(rule["example"]), f"{rule['id']}: el ejemplo no coincide"
