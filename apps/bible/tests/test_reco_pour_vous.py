"""« Pour vous aujourd'hui » (plan V2 §6) : signaux, signets, réglage, précalcul, repli.

Fournisseur d'embeddings « stub » : aucun modèle n'est chargé, les vecteurs des versets sont
posés à la main pour rendre la géométrie lisible :
- axe 0 : suivre Jésus (Luc 9, Luc 10, Actes, Jean 15) ;
- axe 1 : faire la volonté du Père (évangile du jour, Mt 21, 28-32) ;
- axe 2, 3 : autres thèmes.
"""

import datetime

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.bible.models import (
    Book,
    Bookmark,
    Chapter,
    DailyRecommendation,
    ParolePreference,
    ReadingEvent,
    Testament,
    Verse,
)
from apps.bible.services import recommendation_service as reco
from apps.bible.services.reading_signals import reading_events_record
from apps.liturgy.models import LiturgicalDate, Reading
from apps.users.tests.factories import BaseUserFactory

TODAY = datetime.date(2026, 9, 27)
NOW = "2026-09-27 06:00:00"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("frozen"),
]


@pytest.fixture
def frozen():
    with override_settings(EMBEDDING_PROVIDER="stub", BIBLE_EDITION="", LITURGY_ZONE="afrique"):
        with freeze_time(NOW):
            yield


def vec(**axes):
    v = [0.0] * 768
    for key, value in axes.items():
        v[int(key[1:])] = value
    return v


class World:
    pass


@pytest.fixture
def world():
    w = World()
    nt = Testament.objects.create(slug="nouveau", name="Nouveau Testament", order=2)
    w.mt = Book.objects.create(testament=nt, name="Matthieu", slug="matthieu", order=47)
    w.lc = Book.objects.create(testament=nt, name="Luc", slug="luc", order=49)
    w.jn = Book.objects.create(testament=nt, name="Jean", slug="jean", order=50)
    w.ac = Book.objects.create(testament=nt, name="Actes", slug="actes", order=51)
    w.jc = Book.objects.create(testament=nt, name="Jacques", slug="jacques", order=66)

    def chapter(book, number, verses):
        ch = Chapter.objects.create(book=book, number=number, verse_count=len(verses))
        out = {}
        for n, embedding in verses.items():
            out[n] = Verse.objects.create(chapter=ch, number=n, text=f"{book.name} {number}, {n}", embedding=embedding)
        return ch, out

    # Noise on axes 10+ keeps each verse distinct.
    w.lc9, w.lc9v = chapter(w.lc, 9, {n: vec(d0=1.0, **{f"d{10 + n}": 0.1}) for n in range(1, 6)})
    w.lc10, w.lc10v = chapter(w.lc, 10, {n: vec(d0=1.0, d1=0.2, **{f"d{20 + n}": 0.1}) for n in range(1, 4)})
    w.mt7, w.mt7v = chapter(w.mt, 7, {21: vec(d0=0.7, d1=0.7)})
    w.mt21, w.mt21v = chapter(w.mt, 21, {n: vec(d1=1.0, d0=0.3, **{f"d{30 + n - 28}": 0.1}) for n in range(28, 33)})
    w.jn15, w.jn15v = chapter(w.jn, 15, {n: vec(d0=1.0, d2=0.5, **{f"d{40 + n}": 0.1}) for n in range(1, 4)})
    w.ac1, w.ac1v = chapter(w.ac, 1, {n: vec(d0=0.9, d3=0.3, **{f"d{50 + n}": 0.1}) for n in range(1, 4)})
    w.jc1, w.jc1v = chapter(w.jc, 1, {22: vec(d3=1.0)})

    # 26e dimanche du temps ordinaire (année A) : évangile Mt 21, 28-32.
    day = LiturgicalDate.objects.create(date=TODAY, zone="afrique", day_name="26e dimanche du temps ordinaire")
    gospel = Reading.objects.create(liturgical_date=day, type="evangile", citation="Mt 21, 28-32", text="")
    gospel.matched_verses.set(w.mt21v.values())

    w.mt_user = BaseUserFactory(email="marie-therese.diouf@example.sn")
    return w


def lu(user, *, chapter, start=None, end=None, days_ago=0.0, finished=False, cid=None, kind="lu"):
    return ReadingEvent.objects.create(
        user=user,
        client_event_id=cid or f"e-{ReadingEvent.objects.count() + 1}",
        kind=kind,
        chapter=chapter,
        verse_start=start,
        verse_end=end,
        finished=finished,
        occurred_at=timezone.now() - datetime.timedelta(days=days_ago),
    )


def all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from all_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from all_keys(item)


# ─── Service de recommandation ─────────────────────────────────────────────────


def test_decay_halves_every_thirty_days():
    assert reco._decay(0) == 1.0
    assert reco._decay(30) == pytest.approx(0.5)
    assert reco._decay(60) == pytest.approx(0.25)


def test_marie_therese_reading_luke_9(world):
    user = world.mt_user
    lu(user, chapter=world.lc9, start=world.lc9v[1], end=world.lc9v[3], days_ago=1)
    Bookmark.objects.create(user=user, verse=world.lc9v[4], color="jaune")

    payload = reco.recommendation_compute(user=user, ctx=reco.reco_context_build(today=TODAY))

    shown = [payload["verset"], *payload["autres_versets"]]
    assert len(shown) == 3
    # Rien de Luc 9 (lu il y a moins de 60 jours) ; un seul verset par livre.
    assert not {v["id"] for v in shown} & {v.id for v in world.lc9v.values()}
    assert len({v["livre"]["id"] for v in shown}) == 3
    assert "Parce que vous lisez Luc" in payload["raisons"]
    assert payload["lecture_a_continuer"] == {
        "reference": "Luc 9",
        "livre": {"id": world.lc.pk, "nom": "Luc", "slug": "luc"},
        "chapitre": 9,
        "reprendre_au_verset": 3,
    }
    # Actes : livre non commencé le plus proche de ce qu'elle lit.
    assert payload["livre_suggere"]["nom"] == "Actes"
    assert payload["plan_suggere"] is None  # plans de lecture gelés en V1 (bible.avance)
    # Aucun score exposé.
    assert not any("score" in k or k in ("rank", "distance") for k in all_keys(payload))


def test_gospel_of_the_day_bonus_and_reason(world):
    user = world.mt_user
    # Intérêt tourné vers l'obéissance au Père : l'évangile du jour doit ressortir.
    lu(user, chapter=world.mt7, start=world.mt7v[21], days_ago=2)

    payload = reco.recommendation_compute(user=user, ctx=reco.reco_context_build(today=TODAY))

    assert payload["verset"]["livre"]["nom"] == "Matthieu"
    assert payload["verset"]["chapitre"] == 21
    assert payload["raisons"][0] == "En lien avec l'évangile du jour"
    assert payload["raisons"][1] == "Parce que vous lisez Matthieu"


def test_old_reading_no_longer_excluded_but_recent_is(world):
    user = world.mt_user
    lu(user, chapter=world.lc10, days_ago=75)  # hors fenêtre d'exclusion (60 j), dans l'historique (90 j)
    lu(user, chapter=world.lc9, days_ago=1)

    profile = reco.reading_profile_build(user=user, now=timezone.now())

    assert {v.id for v in world.lc9v.values()} <= profile.excluded_verse_ids
    assert not {v.id for v in world.lc10v.values()} & profile.excluded_verse_ids


def test_no_signal_gives_no_payload(world):
    assert reco.recommendation_compute(user=world.mt_user, ctx=reco.reco_context_build(today=TODAY)) is None


def test_stub_zero_vectors_are_ignored(world):
    zero = Verse.objects.create(chapter=world.jc1, number=1, text="sans vecteur", embedding=[0.0] * 768)
    lu(world.mt_user, chapter=world.jc1, start=zero, days_ago=1)

    assert reco.recommendation_compute(user=world.mt_user, ctx=reco.reco_context_build(today=TODAY)) is None


def test_finished_chapter_suggests_the_next_one(world):
    user = world.mt_user
    lu(user, chapter=world.lc9, days_ago=1, finished=True)

    assert reco.continue_reading_get(user=user)["reference"] == "Luc 10"
    assert reco.continue_reading_get(user=user)["reprendre_au_verset"] is None


def test_nightly_recompute_only_active_users_and_is_idempotent(world):
    from apps.bible.tasks import bible_reco_recompute_task

    active, idle, disabled = world.mt_user, BaseUserFactory(), BaseUserFactory()
    lu(active, chapter=world.lc9, days_ago=1)
    lu(idle, chapter=world.lc9, days_ago=40)
    lu(disabled, chapter=world.lc9, days_ago=1)
    ParolePreference.objects.create(user=disabled, personnalisation_parole=False)
    DailyRecommendation.objects.create(user=active, date=TODAY - datetime.timedelta(days=10), payload={})

    first = bible_reco_recompute_task.apply().get()
    second = bible_reco_recompute_task.apply().get()

    assert first["stored"] == second["stored"] == 1
    assert first["purged"] == 1
    assert list(DailyRecommendation.objects.values_list("user_id", "date")) == [(active.pk, TODAY)]


def test_beat_runs_nightly_on_reco_queue():
    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["bible_reco_recompute"]
    assert entry["task"] == "apps.bible.tasks.bible_reco_recompute_task"
    assert entry["options"] == {"queue": "reco"}
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({3}, {30})


# ─── APIs ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(world):
    c = APIClient()
    c.force_authenticate(user=world.mt_user)
    return c


def event(cid, **kw):
    return {"client_event_id": cid, "type": "lu", "occurred_at": "2026-09-27T05:30:00Z", **kw}


def test_events_batch_is_idempotent_and_rejects_unknown_refs(client, world):
    url = reverse("api:bible:reading-events")
    body = {
        "evenements": [
            event("a1", livre_id=world.lc.pk, chapitre=9),
            event("a2", verset_debut_id=world.lc9v[5].pk, verset_fin_id=world.lc9v[2].pk, type="lectio"),
            event("a3", verset_debut_id=999999),
        ]
    }

    first = client.post(url, body, format="json")
    second = client.post(url, body, format="json")

    assert first.status_code == 200, first.data
    assert first.data == {"recus": 3, "enregistres": 2, "rejetes": ["a3"], "personnalisation_parole": True}
    assert second.data["enregistres"] == 0
    ranged = ReadingEvent.objects.get(client_event_id="a2")
    assert (ranged.verse_start.number, ranged.verse_end.number, ranged.chapter_id) == (2, 5, world.lc9.pk)


def test_event_needs_a_reference(client):
    response = client.post(reverse("api:bible:reading-events"), {"evenements": [event("x")]}, format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


def test_future_event_is_clamped_to_now(client, world):
    client.post(
        reverse("api:bible:reading-events"),
        {"evenements": [event("f", livre_id=world.lc.pk, chapitre=9, occurred_at="2027-01-01T00:00:00Z")]},
        format="json",
    )
    assert ReadingEvent.objects.get(client_event_id="f").occurred_at == timezone.now()


def test_delete_history_keeps_bookmarks(client, world):
    lu(world.mt_user, chapter=world.lc9)
    Bookmark.objects.create(user=world.mt_user, verse=world.lc9v[1])
    DailyRecommendation.objects.create(user=world.mt_user, date=TODAY, payload={"verset": None})

    response = client.delete(reverse("api:bible:reading-events"))

    assert response.status_code == 204
    assert not ReadingEvent.objects.exists()
    assert not DailyRecommendation.objects.exists()
    assert Bookmark.objects.count() == 1


def test_bookmark_crud(client, world):
    url = reverse("api:bible:bookmark-list-create")
    created = client.post(url, {"verset_id": world.lc9v[3].pk, "couleur": "jaune", "note": "Porter sa croix"}, format="json")
    assert created.status_code == 201, created.data
    assert created.data["type"] == "surligne"
    assert created.data["reference"] == "Luc 9, 3"

    again = client.post(url, {"verset_id": world.lc9v[3].pk}, format="json")
    assert again.data["id"] == created.data["id"] and again.data["type"] == "signet"

    detail = reverse("api:bible:bookmark-detail", args=[created.data["id"]])
    assert client.patch(detail, {"couleur": "vert"}, format="json").data["couleur"] == "vert"
    assert client.get(url).data["count"] == 1

    other = APIClient()
    other.force_authenticate(user=BaseUserFactory())
    assert other.get(detail).status_code == 404

    assert client.delete(detail).status_code == 204
    assert not Bookmark.objects.exists()


def test_bookmark_unknown_verse(client):
    response = client.post(reverse("api:bible:bookmark-list-create"), {"verset_id": 999999}, format="json")
    assert response.status_code == 404


def test_pour_vous_reads_the_nightly_table(client, world):
    lu(world.mt_user, chapter=world.lc9, start=world.lc9v[1], end=world.lc9v[3], days_ago=1)
    reco.daily_recommendations_recompute(today=TODAY)

    data = client.get(reverse("api:bible:pour-vous")).data

    assert data["personnalise"] is True
    assert data["date"] == "2026-09-27"
    assert data["verset"]["livre"]["nom"] != "Luc" or data["verset"]["chapitre"] != 9
    assert data["lecture_a_continuer"]["reference"] == "Luc 9"


def test_pour_vous_cold_start_serves_the_gospel_verse(client, world):
    data = client.get(reverse("api:bible:pour-vous")).data

    assert data["personnalise"] is False
    assert data["verset"]["reference"] == "Matthieu 21, 28"
    assert data["raisons"] == ["Tiré de l'évangile du jour"]
    assert data["lecture_a_continuer"] is None


def test_disabling_personalisation(client, world):
    DailyRecommendation.objects.create(user=world.mt_user, date=TODAY, payload={"verset": None})
    lu(world.mt_user, chapter=world.lc9)

    put = client.put(reverse("api:bible:parole-preferences"), {"personnalisation_parole": False}, format="json")
    assert put.data == {"personnalisation_parole": False}
    assert not DailyRecommendation.objects.exists()

    posted = client.post(
        reverse("api:bible:reading-events"), {"evenements": [event("z", livre_id=world.lc.pk, chapitre=10)]}, format="json"
    )
    assert posted.data["enregistres"] == 0 and posted.data["personnalisation_parole"] is False
    assert not ReadingEvent.objects.filter(client_event_id="z").exists()

    data = client.get(reverse("api:bible:pour-vous")).data
    assert data["personnalise"] is False and data["personnalisation_parole"] is False
    assert data["lecture_a_continuer"] is None  # l'historique n'est plus utilisé
    assert data["verset"]["reference"] == "Matthieu 21, 28"
    assert client.get(reverse("api:bible:parole-preferences")).data == {"personnalisation_parole": False}


def test_endpoints_require_authentication():
    anonymous = APIClient()
    for name in ("reading-events", "bookmark-list-create", "parole-preferences", "pour-vous"):
        assert anonymous.get(reverse(f"api:bible:{name}")).status_code in (401, 403)


# ─── Conformité ────────────────────────────────────────────────────────────────


def test_record_service_rejects_oversized_batch(world):
    from apps.core.exceptions import ApplicationError

    too_many = [{"client_event_id": str(i), "type": "lu", "occurred_at": timezone.now()} for i in range(201)]
    with pytest.raises(ApplicationError):
        reading_events_record(user=world.mt_user, events=too_many)


def test_account_deletion_forgets_parole_data_and_export_includes_it(world):
    from apps.users.selectors_privacy import personal_data_export
    from apps.users.services_privacy import account_delete

    user = world.mt_user
    lu(user, chapter=world.lc9, start=world.lc9v[1])
    Bookmark.objects.create(user=user, verse=world.lc9v[2], note="à méditer")
    ParolePreference.objects.create(user=user)
    DailyRecommendation.objects.create(user=user, date=TODAY, payload={})

    export = personal_data_export(user=user)["parole"]
    assert export["signets"][0]["verset"] == "Luc 9, 2"
    assert export["historique_de_lecture"][0]["chapitre"] == "Luc 9"

    account_delete(user=user)

    for model in (ReadingEvent, Bookmark, ParolePreference, DailyRecommendation):
        assert not model.objects.filter(user=user).exists()
