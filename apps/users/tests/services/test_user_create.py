"""
Tests de base sur le modèle BaseUser et le manager.
"""


from django.test import TestCase

from apps.users.enums import UserRole
from apps.users.models import BaseUser
from apps.users.tests.factories import AdminUserFactory, BaseUserFactory


class BaseUserManagerTests(TestCase):

    def test_user_with_no_password_is_unusable(self):
        # Arrange / Act
        user = BaseUser.objects.create_user(
            email="nopassword@example.com",
            phone_number="+221771000001",
            role=UserRole.FIDELE,
        )
        # Assert
        self.assertFalse(user.has_usable_password())

    def test_email_normalized_to_lowercase(self):
        user = BaseUser.objects.create_user(
            email="TEST@EXAMPLE.COM",
            phone_number="+221771000002",
            role=UserRole.FIDELE,
            password="StrongPassw0rd!",
        )
        self.assertEqual(user.email, "test@example.com")

    def test_duplicate_email_raises(self):
        BaseUser.objects.create_user(
            email="dup@example.com",
            phone_number="+221771000003",
            role=UserRole.FIDELE,
        )
        with self.assertRaises(Exception):
            BaseUser.objects.create_user(
                email="DUP@example.com",
                phone_number="+221771000004",
                role=UserRole.FIDELE,
            )

    def test_superuser_has_correct_flags(self):
        user = BaseUser.objects.create_superuser(
            email="super@example.com",
            password="SuperPassw0rd!",
        )
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_admin)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_verified)
        self.assertEqual(user.role, UserRole.SUPER_ADMIN)


class BaseUserFactoryTests(TestCase):

    def test_factory_creates_active_verified_fidele(self):
        user = BaseUserFactory()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_verified)
        self.assertEqual(user.role, UserRole.FIDELE)

    def test_admin_factory_has_correct_flags(self):
        admin = AdminUserFactory()
        self.assertTrue(admin.is_admin)
        self.assertTrue(admin.is_staff)
        self.assertEqual(admin.role, UserRole.SUPER_ADMIN)

    def test_emails_are_unique_per_factory_call(self):
        u1 = BaseUserFactory()
        u2 = BaseUserFactory()
        self.assertNotEqual(u1.email, u2.email)

