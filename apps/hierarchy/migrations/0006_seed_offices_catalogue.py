"""Catalogue des capacités (fermé) et des offices du profil « Sénégal » (SRS §6.2, §6.3)."""

from django.db import migrations


def seed(apps, schema_editor):
    from apps.hierarchy.catalogue import load_offices_catalogue

    load_offices_catalogue(
        Capability=apps.get_model("hierarchy", "Capability"),
        OfficeType=apps.get_model("hierarchy", "OfficeType"),
        NodeType=apps.get_model("hierarchy", "NodeType"),
    )


def unseed(apps, schema_editor):
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType.objects.filter(is_system=True, assignments__isnull=True).delete()
    Capability.objects.filter(office_types__isnull=True, overrides__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0005_offices_capabilities_audit")]

    operations = [migrations.RunPython(seed, unseed)]
