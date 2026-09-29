collect_ignore_glob = [
    "apps/testing_examples/*",
    "apps/common/tests/services/test_model_update.py",
]


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_keycloak_reset():
    """Le faux client Keycloak (KEYCLOAK_ADMIN_BACKEND = "fake") repart vide à chaque test."""
    from apps.integrations.keycloak.fake import fake_keycloak

    fake_keycloak().reset()
    yield
