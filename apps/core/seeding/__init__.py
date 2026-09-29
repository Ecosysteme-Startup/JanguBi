"""Données de test réalistes (``seed_realiste``) : registre, contexte, garde-fous, outils partagés."""

from __future__ import annotations

import functools
import pathlib
from typing import Any

DATA_DIR = pathlib.Path(__file__).parent / "data"


@functools.cache
def textes() -> dict[str, Any]:
    import yaml

    with open(DATA_DIR / "textes.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
