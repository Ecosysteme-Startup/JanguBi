"""Données de test réalistes (``seed_realiste``) : échelle petite, sans réseau, médias « aucun » et
« legers ». Garde-fous, registre, invariants, jeu de septembre exact, idempotence et remise à zéro."""

import dataclasses

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.seeding import registry
from apps.core.seeding.context import SCALES

pytestmark = pytest.mark.django_db


@pytest.fixture
def allowed(monkeypatch):
    monkeypatch.setenv("SEED_ALLOWED", "true")
    monkeypatch.delenv("ENV", raising=False)


def seed(*args):
    call_command("seed_realiste", "--profil", "local", "--echelle", "petite", "--hors-ligne", *args)


def test_refused_without_seed_allowed(monkeypatch):
    monkeypatch.delenv("SEED_ALLOWED", raising=False)
    with pytest.raises(CommandError, match="SEED_ALLOWED"):
        seed("--medias", "aucun")


def test_refused_in_production(monkeypatch):
    monkeypatch.setenv("SEED_ALLOWED", "true")
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(CommandError, match="production"):
        seed("--medias", "aucun")


def test_registry_orders_by_phase_and_resolves_dependencies():
    registry.autodiscover()
    names = [s.name for s in registry.ordered({"dons"})]
    assert names[-1] == "dons"
    assert names.index("hierarchie") < names.index("personnes") < names.index("appartenances") < names.index("dons")
    everything = [s.name for s in registry.ordered(None)]
    assert everything.index("dons") < everything.index("sonotheque") < everything.index("ecoutes") < everything.index("audio_reco")
    with pytest.raises(ValueError, match="inconnu"):
        registry.ordered({"module-inexistant"})


def test_registry_extension_point(monkeypatch):
    """Une application ajoutée plus tard (ex. intentions de messe) s'enregistre sans toucher l'orchestrateur."""
    registry.autodiscover()
    monkeypatch.setattr(registry, "REGISTRY", dict(registry.REGISTRY))

    @registry.register
    class IntentionsSeeder(registry.Seeder):
        name = "intentions_test"
        module = "intentions"
        phase = registry.Phase.CONTENUS
        depends = ("appartenances",)

    names = [s.name for s in registry.ordered({"intentions"})]
    assert names[-1] == "intentions_test" and "personnes" in names


def test_petite_without_media_is_complete_verified_idempotent_and_reversible(allowed):
    from apps.audio.models import AudioSource, Track
    from apps.core.models import SeedRecord
    from apps.donations.models import Donation, MonthClosing
    from apps.hierarchy.models import ParishMembership
    from apps.users.models import BaseUser

    seed("--medias", "aucun", "--verifier")  # --verifier lève CommandError si un invariant échoue

    fideles = BaseUser.objects.filter(email__regex=r"\.\d{5}@demo\.jangubi\.sn$")
    assert fideles.count() == 300
    assert ParishMembership.objects.filter(is_primary=True, user__in=fideles).count() == 300
    assert Track.objects.filter(source__in=AudioSource.objects.all(), status="pret").count() == 40
    donations = Donation.objects.count()
    assert 3_500 <= donations <= 4_500
    assert MonthClosing.objects.exists()

    seed("--medias", "aucun")  # second passage : complète sans dupliquer
    assert Donation.objects.count() == donations
    assert BaseUser.objects.filter(pk__in=fideles).count() == 300

    call_command("seed_realiste", "--reset")
    assert not SeedRecord.objects.exists()
    assert not Donation.objects.exists()
    assert not AudioSource.objects.exists()
    # Les personas de seed_demo sont intactes.
    assert BaseUser.objects.filter(email="cure@demo.jangubi.sn").exists()
    assert BaseUser.objects.filter(email__endswith="@demo.jangubi.sn").count() == 12


def test_september_matches_the_spec_dataset(allowed):
    from apps.donations.selectors_analyse import donations_analysis, period_parse
    from apps.hierarchy.models import Node
    from apps.hierarchy.profiles import PILOT_PARISH_CODE

    seed("--medias", "aucun", "--modules", "dons")
    pilot = Node.objects.get(code=PILOT_PARISH_CODE)
    s = donations_analysis(node=pilot, level="paroisse", period=period_parse("mois", "2026-09"))["synthese"]
    assert (s["collecte"], s["en_ligne"], s["especes"]) == (1_214_830, 356_330, 858_500)
    assert (s["nombre_dons_en_ligne"], s["nombre_quetes"]) == (47, 9)


def test_same_seed_gives_same_people(allowed):
    from apps.users.models import BaseUser

    seed("--modules", "socle", "--medias", "aucun")
    first = sorted(BaseUser.objects.filter(email__regex=r"\.\d{5}@").values_list("email", "pk"))
    call_command("seed_realiste", "--reset")
    seed("--modules", "socle", "--medias", "aucun")
    assert sorted(BaseUser.objects.filter(email__regex=r"\.\d{5}@").values_list("email", "pk")) == first


def test_light_media_go_through_the_real_encoder(allowed, monkeypatch):
    """``legers`` : extraits encodés par la vraie chaîne (HLS 3 débits + MP3, forme d'onde)."""
    from apps.audio.models import Track, TrackRendition

    small = dataclasses.replace(SCALES["petite"], pistes=4, ecoutes=400, fideles=40)
    monkeypatch.setitem(SCALES, "petite", small)
    seed("--medias", "legers", "--modules", "audio", "--verifier")
    tracks = Track.objects.all()
    assert tracks.count() == 4
    assert all(t.status == "pret" and t.waveform and 25 <= t.duration_seconds <= 31 for t in tracks)
    assert TrackRendition.objects.filter(kind__startswith="hls_").count() == 12


def test_user_album_feeds_the_chants_with_its_credits(allowed, monkeypatch, tmp_path):
    """``--medias-dossier`` : les pistes de l'album fourni servent de chants, attribution de credits.yaml."""
    import subprocess

    from apps.audio.models import Track

    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=8",
                    str(tmp_path / "01-kyrie.mp3")], check=True)  # fmt: skip
    (tmp_path / "credits.yaml").write_text(
        'album: {titre: "Messe libre", artiste: "Chœur de test", licence: "CC BY 4.0"}\n'
        'pistes:\n  "01-kyrie.mp3": {titre: "Kyrie eleison"}\n',
        encoding="utf-8",
    )
    small = dataclasses.replace(SCALES["petite"], pistes=30, ecoutes=100, fideles=20)  # jusqu'aux chorales
    monkeypatch.setitem(SCALES, "petite", small)
    seed("--medias", "legers", "--modules", "audio", "--medias-dossier", str(tmp_path))
    chants = Track.objects.filter(title="Kyrie eleison")
    assert chants.exists()
    assert all("Chœur de test" in t.description and "CC BY 4.0" in t.description for t in chants)


def _mois_ecoule():
    import datetime

    from django.utils import timezone

    return (timezone.localdate().replace(day=1) - datetime.timedelta(days=1)).replace(day=1)


def test_a_stale_automatic_closing_is_rebuilt_and_reset_with_the_batch(allowed):
    # Recette du 30/09/2026 : la clôture de nuit (03:40) a figé août à 0 sur une base vide, puis le seed
    # a rempli août ; le semeur sautait toute clôture existante → invariant « synthèse » en échec.
    from apps.donations.models import MonthClosing
    from apps.donations.services_cloture import month_close
    from apps.hierarchy.models import Node
    from apps.hierarchy.profiles import PILOT_PARISH_CODE

    seed("--medias", "aucun", "--modules", "socle")
    pilot = Node.objects.get(code=PILOT_PARISH_CODE)
    stale = month_close(node=pilot, month=_mois_ecoule())  # automatique (sans auteur), sur une base vide
    assert stale.totals["collecte"] == 0

    seed("--medias", "aucun", "--modules", "dons")

    from apps.donations.selectors_analyse import month_totals

    rebuilt = MonthClosing.objects.get(node=pilot, month=_mois_ecoule())
    assert rebuilt.pk != stale.pk
    assert rebuilt.totals["collecte"] == month_totals(node=pilot, month=_mois_ecoule())["collecte"] > 0
    call_command("seed_realiste", "--reset")
    assert not MonthClosing.objects.filter(node=pilot, month=_mois_ecoule()).exists()


def test_a_manual_closing_is_never_rebuilt(allowed):
    from apps.donations.models import MonthClosing
    from apps.hierarchy.models import Node
    from apps.hierarchy.profiles import PILOT_PARISH_CODE
    from apps.users.models import BaseUser

    seed("--medias", "aucun", "--modules", "socle")
    pilot = Node.objects.get(code=PILOT_PARISH_CODE)
    econome = BaseUser.objects.filter(email__endswith="@demo.jangubi.sn").first()
    manual = MonthClosing.objects.create(node=pilot, month=_mois_ecoule(), closed_by=econome, totals={"collecte": 0})

    seed("--medias", "aucun", "--modules", "dons")

    manual.refresh_from_db()
    assert manual.totals == {"collecte": 0}


def test_listens_are_seeded_while_tracks_are_still_encoding(allowed):
    # En médias complets l'encodage est asynchrone : au passage des écoutes, les pistes sont encore
    # « en_file ». Filtrer sur « pret » donnait 0 écoute, et le semeur était marqué fait pour toujours.
    from apps.audio.models import PlayEvent, Track
    from apps.core.models import SeedRecord

    seed("--medias", "aucun", "--modules", "audio")
    PlayEvent.objects.all().delete()
    SeedRecord.objects.filter(seeder="ecoutes").delete()
    Track.objects.update(status="en_file")

    seed("--medias", "aucun", "--modules", "audio")

    assert PlayEvent.objects.exists()


def test_a_seeder_that_produced_nothing_is_not_marked_done(allowed):
    from apps.audio.models import PlayEvent, Track
    from apps.core.models import SeedRecord

    seed("--medias", "aucun", "--modules", "audio")
    PlayEvent.objects.all().delete()
    SeedRecord.objects.filter(seeder="ecoutes").delete()
    Track.objects.update(status="echec")  # rien d'écoutable

    seed("--medias", "aucun", "--modules", "audio")

    assert not PlayEvent.objects.exists()
    assert not SeedRecord.objects.filter(seeder="ecoutes", model="_done").exists()
