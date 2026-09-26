"""Adresse du client (derrière le mandataire) et troncature pour le journal d'audit."""

import pytest
from django.test import override_settings
from rest_framework.settings import api_settings

from apps.core.request_context import client_ip, current_client_ip, ip_truncate


@pytest.fixture
def one_proxy():
    with override_settings(REST_FRAMEWORK={"NUM_PROXIES": 1}):
        api_settings.reload()
        yield
    api_settings.reload()


def test_client_ip_takes_the_address_seen_by_the_trusted_proxy(one_proxy):
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "1.1.1.1, 203.0.113.7"}
    assert client_ip(meta) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr_and_rejects_garbage(one_proxy):
    assert client_ip({"REMOTE_ADDR": "198.51.100.4"}) == "198.51.100.4"
    assert client_ip({"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "pas-une-ip"}) is None
    assert client_ip({}) is None


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("203.0.113.77", "203.0.113.0"),
        ("2001:db8:1234:5678::1", "2001:db8:1234::"),
        ("n'importe quoi", None),
        (None, None),
    ],
)
def test_ip_truncate(ip, expected):
    assert ip_truncate(ip) == expected


def test_no_client_ip_outside_a_request():
    assert current_client_ip() is None
