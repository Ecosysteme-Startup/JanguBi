"""Garde c. 848 : aucun service de l'Église n'est conditionné à un don.

Le module dons n'a aucune dépendance avec les demandes d'actes, la messagerie et la confession,
dans un sens comme dans l'autre : aucun appel au don ne peut se glisser dans ces parcours.
"""

import ast
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[2]
PASTORAL = ("documents", "messaging", "confessions")


def _imports(app: str) -> set[str]:
    found: set[str] = set()
    for path in (APPS / app).rglob("*.py"):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
            elif isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("app", PASTORAL)
def test_donations_does_not_depend_on_pastoral_modules(app):
    assert not any(m.startswith(f"apps.{app}") for m in _imports("donations"))


@pytest.mark.parametrize("app", PASTORAL)
def test_pastoral_modules_do_not_depend_on_donations(app):
    assert not any(m.startswith("apps.donations") for m in _imports(app))


@pytest.mark.django_db
def test_no_mass_offering_fund_type():
    from apps.donations.enums import FundKind

    assert not any("messe" in value or "intention" in value for value in FundKind.values)
