"""BUG-B2 — fetch AELF : IntegrityError null « title » dans bible_dailytext.

AELF renvoie « titre »: null (clé présente) pour certaines lectures (psaume) →
`lecture.get("titre", "")` renvoyait None → DailyText.title NOT NULL → IntegrityError.
On coalesce title (et content, même motif) vers "".
"""

import datetime

import pytest
from asgiref.sync import async_to_sync

from apps.bible.models import DailyText
from apps.bible.services.aelf_service import AELFService

D = datetime.date(2026, 6, 4)


@pytest.mark.django_db(transaction=True)
def test_psalm_without_title_does_not_raise_integrity_error():
    # titre=null (psaume) → ne doit PAS planter ; title coalescé en "".
    data = {
        "messes": [
            {
                "lectures": [
                    {
                        "type": "psaume",
                        "titre": None,
                        "contenu": "<p>Seigneur, enseigne-moi tes voies.</p>",
                    }
                ]
            }
        ]
    }

    records = async_to_sync(AELFService()._process_api_response)(D, data)

    assert len(records) == 1
    psalm = DailyText.objects.get(date=D, category="psaume")
    assert psalm.title == ""
    assert "enseigne-moi" in psalm.content


@pytest.mark.django_db(transaction=True)
def test_reading_without_content_does_not_raise():
    # contenu=null (même motif clé-présente-valeur-null) → content coalescé en "".
    data = {"messes": [{"lectures": [{"type": "lecture", "titre": None, "contenu": None}]}]}

    records = async_to_sync(AELFService()._process_api_response)(D, data)

    assert len(records) == 1
    dt = DailyText.objects.get(date=D, category="lecture")
    assert dt.title == ""
    assert dt.content == ""
