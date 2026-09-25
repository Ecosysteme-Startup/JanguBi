import pytest


@pytest.fixture(autouse=True)
def _adults(monkeypatch):
    """Les tests historiques de la messagerie ne portent pas sur la majorité : la règle RG-13
    (date de naissance obligatoire, 18 ans) est couverte par test_pretre_v1.py."""
    import apps.messaging.services as services

    if getattr(_adults, "enabled", True):
        monkeypatch.setattr(services, "adult_check", lambda *, user: None)
