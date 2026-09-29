"""Garde-fous du semis (plan §2) : jamais en production, jamais sans accord explicite, aucune tâche
(push, e-mail, webhook) envoyée pendant le semis sauf celles qu'on autorise nommément."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from django.conf import settings

TRUE = {"1", "true", "yes", "oui", "on"}


class SeedRefused(Exception):
    pass


def environment() -> str:
    explicit = os.environ.get("ENV") or os.environ.get("DJANGO_ENV")
    if explicit:
        return explicit.lower()
    declared = getattr(settings, "JANGUBI_ENVIRONMENT", "")
    if declared:
        return str(declared).lower()
    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return "production" if module.endswith(".production") else "local"


def check_allowed(*, profil: str) -> None:
    env = environment()
    if env in {"production", "prod"}:
        raise SeedRefused("Refusé : environnement de production. Les données de test n'y vont jamais.")
    allowed = str(os.environ.get("SEED_ALLOWED", getattr(settings, "SEED_ALLOWED", ""))).lower() in TRUE
    if not allowed:
        raise SeedRefused("Refusé : SEED_ALLOWED n'est pas vrai. Lancez avec SEED_ALLOWED=true (make seed-realiste).")
    if profil == "recette" and env not in {"staging", "recette"}:
        # Accepté (recette reproduite en local), mais signalé.
        pass


@contextlib.contextmanager
def tasks_muted(allow: tuple[str, ...] = ()) -> Iterator[list[str]]:
    """Aucune tâche Celery n'est publiée (pas de push, pas d'e-mail) sauf celles de ``allow``
    (ex. l'encodage audio pour ``--medias complets``). Renvoie la liste des tâches écartées."""
    from celery.app.task import Task

    dropped: list[str] = []
    original = Task.apply_async

    def apply_async(self: Any, *args: Any, **kwargs: Any) -> Any:
        if self.name in allow:
            return original(self, *args, **kwargs)
        dropped.append(self.name)
        return None

    Task.apply_async = apply_async  # type: ignore[method-assign]
    try:
        yield dropped
    finally:
        Task.apply_async = original  # type: ignore[method-assign]
