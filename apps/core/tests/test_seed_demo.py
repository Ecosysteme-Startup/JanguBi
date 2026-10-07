"""Commande de démonstration V1 : idempotente et réversible."""

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent_and_reversible():
    from apps.confessions.models import ConfessionSlot
    from apps.documents.models import DocumentRequest
    from apps.hierarchy import authz
    from apps.hierarchy.models import Node
    from apps.hierarchy.profiles import PILOT_PARISH_CODE
    from apps.news.models import Article
    from apps.users.models import BaseUser

    call_command("seed_hierarchy_profile", "senegal")
    call_command("seed_demo")
    call_command("seed_demo")

    parish = Node.objects.get(code=PILOT_PARISH_CODE)
    cure = BaseUser.objects.get(email="cure@demo.jangubi.sn")
    assert authz.peut(cure, "actes.traiter", parish)
    assert Article.objects.filter(author=cure).count() == 3
    assert DocumentRequest.objects.filter(target_node=parish).count() == 1
    assert ConfessionSlot.objects.exists()
    # Dons (ADR-017) : collecte active, trois fonds paroissiaux et la quête impérée de Brin.
    from apps.donations.models import Fund

    assert parish.donation_activation.enabled
    assert Fund.objects.filter(node=parish, parent__isnull=True).count() == 3
    assert Fund.objects.get(node=parish, kind="quete_imperee").destination == "curie"

    # JB-WEB-040 : la paroisse pilote est sous un doyenné et le doyen ne voit que son doyenné.
    deanery = parish.get_parent()
    assert deanery.type.code == "doyenne"
    doyen = BaseUser.objects.get(email="doyen@demo.jangubi.sn")
    assert authz.peut(doyen, "actes.superviser", parish)  # paroisse dans le doyenné du doyen
    diocese = next(n for n in reversed(parish.get_ancestors()) if n.type.code == "diocese")
    assert not authz.peut(doyen, "actes.superviser", diocese)  # rien au-dessus de son doyenné

    call_command("seed_demo", "--reset")
    assert not BaseUser.objects.filter(email__endswith="@demo.jangubi.sn").exists()
    assert not Fund.objects.exists()
    # La paroisse pilote survit au reset, rerattachée sous un diocèse.
    pilot = Node.objects.get(code=PILOT_PARISH_CODE)
    assert pilot.get_parent().type.code == "diocese"
    assert not Node.objects.filter(code="DEMO-DOYENNE").exists()
