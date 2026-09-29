import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.donations import services
from apps.donations.models import DonationActivation, Fund
from apps.donations.providers.fake import FakeProvider
from apps.hierarchy.tests.factories import Tree, make_place, nominate, person, priest
from apps.users.models import Profile
from apps.users.tests.factories import platform_identity

TODAY = datetime.date(2026, 9, 27)
NOW = "2026-09-27 09:00:00"  # dimanche 27 septembre 2026, Africa/Dakar = UTC


def named(user: Any, first: str, last: str) -> Any:
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    user.refresh_from_db()
    return user


def client_for(user: Any = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tree(db) -> Tree:
    return Tree()


@pytest.fixture
def world(tree):
    w = SimpleNamespace(tree=tree)
    w.sd, w.st, w.dakar, w.thies = tree.saint_dominique, tree.sainte_therese, tree.dakar, tree.thies
    w.place = make_place(w.sd, "Église Saint-Dominique")
    w.cure = named(priest("cure@sd.sn"), "Joseph", "Sarr")
    w.econome = named(person("econome@sd.sn"), "Anne", "Mendy")
    w.secretaire = named(person("secretaire@sd.sn"), "Marie", "Faye")
    w.fidele = named(person("awa@test.sn"), "Awa", "Diop")
    w.autre_cure = priest("cure@st.sn")
    w.eveque = person("eveque@dakar.sn", ordre="eveque")
    w.econome_dio = person("econome@dakar.sn")
    w.doyen = priest("doyen@pm.sn")
    w.platform = platform_identity(person("admin@numerisen.sn"))
    nominate(w.cure, "cure", w.sd)
    nominate(w.econome, "econome_paroissial", w.sd)
    nominate(w.secretaire, "secretaire_paroissial", w.sd)
    nominate(w.autre_cure, "cure", w.st)
    nominate(w.eveque, "eveque_diocesain", w.dakar)
    nominate(w.econome_dio, "econome_diocesain", w.dakar)
    nominate(w.doyen, "doyen", tree.doyenne)
    DonationActivation.objects.create(
        node=w.sd, enabled=True, authorization_ref="ARCH-DAK-2026-041", authorization_date=TODAY, allocation_key="SD01",
        receipt_prefix="SD",
    )
    return w


def open_fund(world: Any, *, kind: str = "quete_dominicale", title: str = "Quête du dimanche 27 septembre", **kw: Any) -> Fund:
    fund = services.fund_create(actor=world.cure, node=world.sd, kind=kind, title=title, **kw)
    return services.fund_publish(fund=fund, actor=world.cure)


@pytest.fixture
def fund(world):
    return open_fund(world)


def pay(donation: Any, *, status: str = "completed", amount: int | None = None, method: str = "wave", fee: int | None = None):
    """Simule l'agrégateur puis poste la notification signée ; renvoie la réponse HTTP."""
    attempt = donation.attempts.get()
    headers, body = FakeProvider.simulate(attempt.external_ref, status, amount=amount, method=method, fee=fee)
    extra: dict[str, Any] = {f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()}
    return client_for().post("/api/v1/dons/webhooks/fake/", data=body, content_type="application/json", **extra)


@pytest.fixture
def sept(world):
    """Jeu de référence de septembre 2026 (spec §2), sous le temps figé au dim. 27 septembre, 20 h."""
    from apps.donations import apis
    from apps.donations.tests import dataset_septembre

    # Modules HTTP importés avant le gel du temps : sinon DRF garderait l'horloge figée (quotas).
    assert apis.AnalysisApi is not None
    with freeze_time("2026-09-27 20:00:00"):
        yield dataset_septembre.build(world)
