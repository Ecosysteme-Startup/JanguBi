"""Manager du modèle BaseUser."""

import pytest

from apps.users.models import BaseUser

pytestmark = pytest.mark.django_db


def test_user_without_password_is_unusable():
    assert not BaseUser.objects.create_user(email="nopassword@example.com").has_usable_password()


def test_email_normalized_to_lowercase():
    assert BaseUser.objects.create_user(email="TEST@EXAMPLE.COM").email == "test@example.com"


def test_duplicate_email_raises():
    BaseUser.objects.create_user(email="dup@example.com")
    with pytest.raises(Exception):
        BaseUser.objects.create_user(email="DUP@example.com")


def test_superuser_is_only_a_django_admin_account():
    from apps.hierarchy.authz import is_platform_admin

    user = BaseUser.objects.create_superuser(email="super@example.com", password="SuperPassw0rd!")
    assert user.is_active and user.is_staff and user.is_superuser
    assert not is_platform_admin(user)  # ADR-015 : seul le rôle Keycloak platform_admin compte
