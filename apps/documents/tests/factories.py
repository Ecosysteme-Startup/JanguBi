"""Fabriques de test des demandes d'actes."""

import datetime

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.documents.models import DocumentRequest
from apps.files.models import File
from apps.users.tests.factories import BaseUserFactory


class DocumentRequestFactory(DjangoModelFactory):
    """Demande soumise (écriture directe, sans passer par le service)."""

    class Meta:
        model = DocumentRequest

    requester = factory.SubFactory(BaseUserFactory)
    reference = factory.Sequence(lambda n: f"DOC-20260925-{n:06d}")
    document_type = DocumentRequest.DocumentType.BAPTISM
    reason = DocumentRequest.RequestReason.PERSONAL
    status = DocumentRequest.Status.SUBMITTED
    requester_last_name = factory.Sequence(lambda n: f"Diallo{n}")
    requester_first_names = factory.Sequence(lambda n: f"Aminata{n}")
    date_of_birth = datetime.date(1990, 1, 1)
    place_of_birth = "Dakar"
    contact_phone = factory.Sequence(lambda n: f"+22177{n:07d}")
    contact_email = factory.Sequence(lambda n: f"contact{n}@example.com")
    father_last_name = "Diallo"
    mother_last_name = "Ndiaye"
    target_node = factory.LazyFunction(lambda: _test_parish())
    sacrament_approximate_date = "2005"
    sacrament_location = "Dakar"
    consent_given = True


class ValidFileFactory(DjangoModelFactory):
    """Fichier finalisé (``is_valid``)."""

    class Meta:
        model = File

    original_file_name = factory.Sequence(lambda n: f"piece-{n}.pdf")
    file_name = factory.Sequence(lambda n: f"piece-{n}.pdf")
    file_type = "application/pdf"
    uploaded_by = factory.SubFactory(BaseUserFactory)
    upload_finished_at = factory.LazyFunction(timezone.now)


def _test_parish():
    from apps.hierarchy.models import Node
    from apps.hierarchy.tests.factories import make_node

    parish = Node.objects.filter(code="DOC-TEST-PAR").first()
    if parish is None:
        province = make_node("province", "Province de test (actes)", code="DOC-TEST-PROV")
        diocese = make_node("diocese", "Diocèse de test (actes)", province, code="DOC-TEST-DIO")
        parish = make_node("paroisse", "Paroisse de test (actes)", diocese, code="DOC-TEST-PAR")
    return parish
