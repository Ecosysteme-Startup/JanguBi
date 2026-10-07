"""
Tests de non-régression sur le rate limiting du login.

Contexte — la faille corrigée : DRF construit l'identité de l'appelant dans
`BaseThrottle.get_ident()`. Quand `NUM_PROXIES` vaut `None` (le défaut), il
concatène TOUT l'en-tête `X-Forwarded-For`, que le client contrôle. Il suffisait
donc de faire varier cet en-tête à chaque requête pour tomber dans un seau
différent : le quota annoncé de 10 tentatives/minute ne s'appliquait jamais, et
la force brute sur le login passait outre.

Avec `NUM_PROXIES = 1`, DRF ne retient que la DERNIÈRE adresse de la chaîne —
celle écrite par notre propre Traefik, qu'un client ne peut pas forger.
"""

import pytest
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from apps.core.throttling import LoginRateThrottle


@pytest.fixture
def throttle():
    return LoginRateThrottle()


@pytest.fixture
def factory():
    return APIRequestFactory()


def test_num_proxies_is_configured():
    """Sans ce réglage, tous les autres tests de ce fichier deviennent faux :
    DRF retomberait sur l'en-tête brut, contrôlé par le client."""
    assert api_settings.NUM_PROXIES is not None, (
        "NUM_PROXIES doit être défini : à None, l'identité de throttling est "
        "dérivée de l'intégralité de X-Forwarded-For, donc forgeable."
    )


def test_forged_forwarded_for_does_not_change_identity(throttle, factory):
    """Le cœur de la faille : deux requêtes venant du MÊME client, qui mentent
    différemment sur X-Forwarded-For, doivent rester dans le même seau."""
    # Arrange — même proxy réel (dernière adresse), préfixe forgé différent.
    first = factory.post(
        "/api/auth/login/",
        HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.7",
        REMOTE_ADDR="203.0.113.7",
    )
    second = factory.post(
        "/api/auth/login/",
        HTTP_X_FORWARDED_FOR="2.2.2.2, 203.0.113.7",
        REMOTE_ADDR="203.0.113.7",
    )

    # Act
    first_ident = throttle.get_ident(first)
    second_ident = throttle.get_ident(second)

    # Assert
    assert first_ident == second_ident == "203.0.113.7"


def test_distinct_clients_keep_distinct_identities(throttle, factory):
    """Le revers : le cloisonnement doit rester réel entre deux clients
    différents, sinon on limiterait tout le monde d'un coup."""
    # Arrange
    alice = factory.post(
        "/api/auth/login/",
        HTTP_X_FORWARDED_FOR="198.51.100.4",
        REMOTE_ADDR="10.0.0.1",
    )
    bob = factory.post(
        "/api/auth/login/",
        HTTP_X_FORWARDED_FOR="198.51.100.9",
        REMOTE_ADDR="10.0.0.1",
    )

    # Act & Assert
    assert throttle.get_ident(alice) != throttle.get_ident(bob)


def test_class_does_not_hardcode_its_own_rate():
    """La classe redéfinissait `THROTTLE_RATES` en dur, ce qui rendait le
    réglage par settings inopérant alors que sa docstring l'annonçait."""
    assert "THROTTLE_RATES" not in LoginRateThrottle.__dict__, (
        "THROTTLE_RATES ne doit plus être redéfini sur la classe : le taux vient des settings."
    )


def test_login_scope_is_declared_in_active_settings(throttle):
    """La portée `login` doit exister dans les réglages ACTIFS, quels qu'ils soient.

    Ce test vient d'une panne réelle : le taux a été déplacé de la classe vers
    `DEFAULT_THROTTLE_RATES` (base.py), mais `config/django/test.py` REMPLACE ce
    dictionnaire au lieu de le compléter. La portée manquait donc sous les
    réglages de test, et DRF levait `ImproperlyConfigured: No default throttle
    rate set for 'login' scope` — tous les tests de connexion tombaient. Rouge en
    CI, invisible en local, qui tourne sous `base`.

    On n'assère pas une VALEUR (la suite neutralise volontairement les quotas à
    `None`), mais la PRÉSENCE de la clé : c'est elle dont l'absence casse tout.
    """
    assert "login" in api_settings.DEFAULT_THROTTLE_RATES, (
        "La portée 'login' doit être déclarée dans DEFAULT_THROTTLE_RATES de "
        "CHAQUE module de réglages — test.py remplace le dictionnaire de base."
    )
    # Ne doit pas lever : c'est exactement l'appel qui échouait.
    throttle.get_rate()
