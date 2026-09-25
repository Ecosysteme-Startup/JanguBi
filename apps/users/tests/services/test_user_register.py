"""
Tests unitaires — inscription utilisateur.

Couvre :
  - user_register_fidele : happy path, email dupliqué, mot de passe faible,
    profil créé, audit log, email envoyé, token stocké
  - user_create_by_admin : super_admin crée un compte, droits insuffisants,
    rôle invalide, email dupliqué, audit log
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.core.exceptions import ApplicationError
from apps.users.enums import UserRole
from apps.users.models import Profile, SecurityAuditLog
from apps.users.services import user_create_by_admin, user_register_fidele
from apps.users.tests.factories import AdminUserFactory, BaseUserFactory, StaffUserFactory

PATCH_EMAIL = "apps.users.services._send_email_safe"
PATCH_TOKEN = "apps.users.services.token_store"

CACHE_SETTINGS = {
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
}


@override_settings(**CACHE_SETTINGS)
class UserRegisterFideleTests(TestCase):

    def setUp(self):
        cache.clear()

    VALID_DATA = {
        "email": "alice@example.com",
        "phone_number": "+221771234567",
        "password": "StrongPassw0rd!",
        "first_name": "Alice",
        "last_name": "Dupont",
        "title": "MRS",
    }

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_creates_inactive_unverified_user(self, mock_email, mock_token):
        # Arrange / Act
        user = user_register_fidele(**self.VALID_DATA)
        # Assert
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_verified)

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_role_is_fidele(self, mock_email, mock_token):
        user = user_register_fidele(**self.VALID_DATA)
        self.assertEqual(user.role, UserRole.FIDELE)

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_profile_created(self, mock_email, mock_token):
        user = user_register_fidele(**self.VALID_DATA)
        self.assertTrue(Profile.objects.filter(user=user).exists())

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_audit_log_created(self, mock_email, mock_token):
        user = user_register_fidele(**self.VALID_DATA)
        self.assertTrue(SecurityAuditLog.objects.filter(user=user).exists())

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_email_normalized_lowercase(self, mock_email, mock_token):
        data = {**self.VALID_DATA, "email": "Alice@EXAMPLE.COM"}
        user = user_register_fidele(**data)
        self.assertEqual(user.email, "alice@example.com")

    def test_duplicate_email_is_silent_and_notifies_owner(self):
        # Anti-énumération : aucune erreur visible, le titulaire de l'adresse est prévenu.
        BaseUserFactory(email="alice@example.com")
        with patch(PATCH_EMAIL) as send, patch(PATCH_TOKEN):
            result = user_register_fidele(**self.VALID_DATA)
        self.assertIsNone(result)
        self.assertEqual(send.call_args.args[0], "account_exists")

    def test_weak_password_raises(self):
        data = {**self.VALID_DATA, "password": "123"}
        with self.assertRaises(ApplicationError):
            with patch(PATCH_EMAIL), patch(PATCH_TOKEN):
                user_register_fidele(**data)

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_verification_email_sent(self, mock_email, mock_token):
        user_register_fidele(**self.VALID_DATA)
        mock_email.assert_called_once()
        args, _ = mock_email.call_args
        self.assertEqual(args[0], "email_verification")

    @patch(PATCH_TOKEN)
    @patch(PATCH_EMAIL)
    def test_token_stored_for_email_verify_action(self, mock_email, mock_token):
        user_register_fidele(**self.VALID_DATA)
        mock_token.assert_called_once()
        call_args = mock_token.call_args
        self.assertEqual(call_args[0][0], "email_verify")


@override_settings(**CACHE_SETTINGS)
class UserCreateByAdminTests(TestCase):

    def setUp(self):
        cache.clear()
        self.admin = AdminUserFactory()

    STAFF_DATA = {
        "email": "staff@example.com",
        "phone_number": "+221779999999",
        "role": UserRole.PARISH_ADMIN,
        "first_name": "Bob",
        "last_name": "Staff",
    }

    @patch(PATCH_EMAIL)
    def test_creates_active_verified_account(self, mock_email):
        # Arrange / Act
        user = user_create_by_admin(**self.STAFF_DATA, performed_by=self.admin)
        # Assert
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_verified)
        self.assertEqual(user.role, UserRole.PARISH_ADMIN)

    @patch(PATCH_EMAIL)
    def test_sends_credentials_email(self, mock_email):
        user_create_by_admin(**self.STAFF_DATA, performed_by=self.admin)
        mock_email.assert_called_once()
        args, _ = mock_email.call_args
        self.assertEqual(args[0], "admin_created_account")

    @patch(PATCH_EMAIL)
    def test_super_admin_can_create_any_role(self, mock_email):
        user = user_create_by_admin(
            **{**self.STAFF_DATA, "email": "diocese@example.com", "role": UserRole.DIOCESE_ADMIN},
            performed_by=self.admin,
        )
        self.assertEqual(user.role, UserRole.DIOCESE_ADMIN)
        self.assertTrue(user.is_admin)

    def test_non_super_admin_cannot_create_account(self):
        # Arrange
        staff = StaffUserFactory()
        # Act & Assert
        with self.assertRaises(ApplicationError) as ctx:
            user_create_by_admin(**self.STAFF_DATA, performed_by=staff)
        self.assertIn("Super Admin", str(ctx.exception))

    def test_invalid_role_raises(self):
        with self.assertRaises(ApplicationError):
            user_create_by_admin(
                **{**self.STAFF_DATA, "role": "role_inexistant"},
                performed_by=self.admin,
            )

    def test_duplicate_email_raises(self):
        # Arrange
        BaseUserFactory(email="staff@example.com")
        # Act & Assert
        with self.assertRaises(ApplicationError):
            with patch(PATCH_EMAIL):
                user_create_by_admin(**self.STAFF_DATA, performed_by=self.admin)

    @patch(PATCH_EMAIL)
    def test_audit_log_created(self, mock_email):
        user = user_create_by_admin(**self.STAFF_DATA, performed_by=self.admin)
        self.assertTrue(SecurityAuditLog.objects.filter(user=user).exists())
