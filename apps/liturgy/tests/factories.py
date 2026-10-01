"""
Factories for liturgy app tests.
Uses factory_boy + DjangoModelFactory as per HackSoft Styleguide.
"""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.liturgy.models import AelfDataEntry, AelfResource, LiturgicalDate, Office, Reading


class LiturgicalDateFactory(DjangoModelFactory):
    """Creates a LiturgicalDate anchored to a realistic date/zone pair."""

    class Meta:
        model = LiturgicalDate
        django_get_or_create = ("date", "zone")

    date = factory.Sequence(lambda n: (timezone.now().date().replace(day=1 + (n % 28))))
    zone = "afrique"
    day_name = factory.Sequence(lambda n: f"Lundi de la semaine {n}")
    season = "Temps Ordinaire"
    mystery = ""
    notes = "vert"


class AelfResourceFactory(DjangoModelFactory):
    """Creates an AelfResource linked to a LiturgicalDate."""

    class Meta:
        model = AelfResource

    liturgical_date = factory.SubFactory(LiturgicalDateFactory)
    audio_url = "https://aelf.org/audio/sample.mp3"
    youtube_url = "https://www.youtube.com/watch?v=sample"


class ReadingFactory(DjangoModelFactory):
    """Creates a Reading (Mass lecture) linked to a LiturgicalDate."""

    class Meta:
        model = Reading
        django_get_or_create = ("liturgical_date", "type", "citation")

    liturgical_date = factory.SubFactory(LiturgicalDateFactory)
    type = factory.Sequence(lambda n: f"lecture{n % 3 + 1}")
    citation = factory.Sequence(lambda n: f"Lc {n + 1}, 1-10")
    text = factory.Sequence(lambda n: f"Texte de la lecture numéro {n}.")
    raw_metadata = factory.LazyAttribute(lambda o: {"type": o.type, "ref": o.citation, "contenu": o.text})


class OfficeFactory(DjangoModelFactory):
    """Creates an Office (Liturgy of the Hours) linked to a LiturgicalDate."""

    class Meta:
        model = Office
        django_get_or_create = ("liturgical_date", "office_type")

    liturgical_date = factory.SubFactory(LiturgicalDateFactory)
    office_type = "laudes"
    hymn = "Voici le jour que fit le Seigneur."
    psalms = factory.LazyFunction(
        lambda: [{"number": 1, "antienne": "Antienne test", "psaume": {"texte": "Psaume test"}}]
    )
    canticle = "Cantique de Zacharie — Béni soit le Seigneur."
    readings = factory.LazyFunction(lambda: [{"titre": "Lecture courte", "texte": "Texte court"}])
    intercessions = "Seigneur, exauce-nous."
    raw_metadata = factory.LazyFunction(lambda: {})


class AelfDataEntryFactory(DjangoModelFactory):
    """Creates a raw AelfDataEntry for audit/rollback testing."""

    class Meta:
        model = AelfDataEntry

    source_endpoint = "/v1/informations"
    date = factory.LazyFunction(lambda: timezone.now().date())
    zone = "afrique"
    raw_json = factory.LazyFunction(lambda: {"informations": {"jour": "Lundi", "temps": "Temps Ordinaire"}})
