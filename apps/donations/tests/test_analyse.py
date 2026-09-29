"""V2 §5.3 : GET staff/dons/analyse/ — paroisse (exact) et diocèse (arrondi, alphabétique, sans nom).

Jeu de référence : spec ECRANS-TABLEAU-DE-BORD-DONS §2 (Saint-Dominique, septembre 2026)."""

import datetime

import pytest

from apps.core.exceptions import ApplicationError
from apps.donations import selectors_analyse
from apps.donations.enums import DonationChannel, DonationStatus, FundDestination, FundKind, FundStatus
from apps.donations.models import Donation, DonationActivation, Fund
from apps.donations.tests.conftest import client_for, named
from apps.hierarchy.tests.factories import make_node

pytestmark = pytest.mark.django_db
URL = "/api/v1/staff/dons/analyse/"


def analyse(user, node, niveau="paroisse", **params):
    query = {"niveau": niveau, "noeud": str(node.pk), "periode": "mois", "date": "2026-09", **params}
    return client_for(user).get(URL, query)


def test_parish_synthesis_matches_the_reference_dataset(world, sept):
    response = analyse(world.econome, world.sd)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["niveau"] == "paroisse" and body["confidentialite"]["arrondi"] == 1
    assert body["periode"] == {"type": "mois", "code": "2026-09", "debut": "2026-09-01", "fin": "2026-09-30",
                               "libelle": "septembre 2026"}  # fmt: skip
    s = body["synthese"]
    assert (s["collecte"], s["en_ligne"], s["especes"]) == (1_214_830, 356_330, 858_500)
    assert (s["nombre_dons_en_ligne"], s["nombre_quetes"]) == (47, 9)
    assert s["par_destination"] == {"paroisse": 540_305, "curie": 674_525}
    assert [(t["type"], t["en_ligne"], t["especes"], t["total"], t["part"]) for t in s["par_type_fonds"]] == [
        ("quete_dominicale", 47_405, 212_500, 259_905, 21),
        ("quete_imperee", 28_525, 646_000, 674_525, 56),
        ("campagne", 236_400, 0, 236_400, 19),
        ("contribution_annuelle", 44_000, 0, 44_000, 4),
    ]
    online, cash = s["par_canal"]
    assert (online["canal"], online["total"], online["part"], cash["total"], cash["part"]) == (
        "en_ligne", 356_330, 29, 858_500, 71
    )
    assert [(x["source"], x["total"], x["nombre"]) for x in online["sources"]] == [
        ("app_ios", 61_500, 8), ("app_android", 199_000, 26), ("web", 95_830, 13)
    ]
    assert [(m["moyen"], m["total"], m["nombre"]) for m in s["par_moyen"]] == [
        ("wave", 208_450, 29), ("orange_money", 106_380, 14), ("free_money", 0, 0), ("carte", 41_500, 4)
    ]
    assert [(p["nom"], p["total"], p["nombre"]) for p in s["par_lieu"]] == [
        ("Église Saint-Dominique", 775_000, 7),
        ("Chapelle de la Cité universitaire", 83_500, 2),
        ("Lieu non renseigné", 356_330, 47),
    ]
    assert [f["titre"] for f in s["par_fonds"]] == [
        "Quête dominicale", "Quête impérée · Grand Séminaire de Brin", "Toiture de la chapelle",
        "Contribution annuelle 2026",
    ]  # fmt: skip


def test_weekly_trend_uses_the_value_date(world, sept):
    body = analyse(world.cure, world.sd).json()
    trend = body["tendance"]
    assert trend["grain"] == "semaine"
    assert [(p["libelle"], p["total"]) for p in trend["points"]] == [
        ("au dim. 6", 71_500), ("au dim. 13", 84_250), ("au dim. 20", 297_805), ("au dim. 27", 761_275)
    ]
    assert trend["points"][3]["par_type_fonds"] == {
        "quete_dominicale": 38_500, "quete_imperee": 674_525, "campagne": 40_250, "contribution_annuelle": 8_000
    }
    assert any("depuis le 20 septembre" in note for note in body["notes"])
    assert any("an dernier disponible à partir de juin 2027" in note for note in body["notes"])  # campagne dès juin


def test_to_do_is_sorted_by_due_date_and_typed(world, sept):
    todo = analyse(world.econome, world.sd).json()["a_traiter"]
    assert [(t["type"], t["echeance"], t["montant"]) for t in todo] == [
        ("paiements_en_attente", "2026-09-28", 18_000),
        ("quete_a_confirmer", "2026-09-29", 64_000),
        ("especes_a_deposer", "2026-10-03", 646_000),
        ("remise_curie", "2026-10-04", 646_000),
    ]
    assert todo[0]["nombre"] == 3 and todo[0]["depuis"].startswith("2026-09-27T01:00")


def test_treasury_payments_and_campaign(world, sept):
    body = analyse(world.econome, world.sd).json()
    online, cash = body["tresorerie"]["en_ligne"], body["tresorerie"]["especes"]
    assert (online["paye"], online["frais"], online["net"]) == (356_330, 7_120, 349_210)
    assert (online["reverse"], online["en_attente_reversement"], online["net_pour_100"]) == (301_480, 47_730, 98)
    assert cash == {"validees": 858_500, "deposees": 212_500, "en_caisse": 646_000, "a_confirmer": 64_000}
    assert body["paiements"] == {"lances": 58, "confirmes": 47, "en_attente": 3, "echoues": 4, "expires": 4,
                                 "taux_confirmation": 81}  # fmt: skip
    (campaign,) = body["campagnes"]
    assert (campaign["reuni"], campaign["objectif"], campaign["part"], campaign["nombre"]) == (
        1_186_400, 4_500_000, 26, 57
    )
    assert campaign["periode"] == 236_400 and campaign["rythme_hebdo"] == 59_100
    assert body["paroisses"] is None


def test_no_donor_name_anywhere(world, sept):
    fidele = named(world.fidele, "Marie-Thérèse", "Diouf")
    Donation.objects.filter(pk=sept.online[0].pk).update(donor=fidele)
    for user, node, niveau in [(world.cure, world.sd, "paroisse"), (world.econome_dio, world.dakar, "diocese")]:
        text = analyse(user, node, niveau).content.decode()
        assert "Diouf" not in text and "Marie-Th" not in text and "donor" not in text


def test_diocese_view_is_rounded_alphabetical_and_aggregated(world, sept):
    response = analyse(world.econome_dio, world.dakar, "diocese")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["confidentialite"] == {"arrondi": 1000, "noms_donateurs": False, "ordre_paroisses": "alphabetique",
                                       "tri_par_montant": False}  # fmt: skip
    s = body["synthese"]
    assert (s["collecte"], s["en_ligne"], s["especes"]) == (1_215_000, 356_000, 859_000)
    assert s["par_destination"] == {"paroisse": 540_000, "curie": 675_000}
    assert s["par_fonds"] is None and s["par_lieu"] is None
    assert [t["total"] for t in s["par_type_fonds"]] == [260_000, 675_000, 236_000, 44_000]
    assert [t["part"] for t in s["par_type_fonds"]] == [21, 56, 19, 4]  # sur les valeurs exactes
    paroisses = body["paroisses"]
    assert paroisses["compteurs"] == {"engagees": 5, "collecte_ouverte": 1, "en_preparation": 4}
    assert [p["nom"] for p in paroisses["lignes"]] == [
        "Cathédrale Notre-Dame-des-Victoires", "Notre-Dame des Anges de Ouakam", "Saint-Dominique",
        "Saint-Joseph de Médina", "Sainte-Thérèse de Grand-Dakar",
    ]  # fmt: skip
    sd = paroisses["lignes"][2]
    assert (sd["statut_collecte"], sd["collecte"], sd["part_en_ligne"], sd["quetes_a_valider"], sd["evolution"]) == (
        "ouverte", 1_215_000, 29, 1, None
    )
    assert paroisses["lignes"][0]["collecte"] is None
    (imperee,) = body["quetes_imperees"]
    assert imperee["echeance"] == "2026-10-04"
    assert imperee["paroisses"] == [{
        "id": str(world.sd.pk), "nom": "Saint-Dominique", "en_ligne": 28_525, "especes": 646_000, "total": 674_525,
        "remis": 0, "remise_declaree": 0, "reste_a_remettre": 646_000, "part_remise": 0,
    }]  # fmt: skip
    assert [(t["type"], t["echeance"]) for t in body["a_traiter"]] == [
        ("quete_a_confirmer", "2026-09-29"), ("remise_curie", "2026-10-04")
    ]
    assert [p["total"] for p in body["tendance"]["points"]] == [72_000, 84_000, 298_000, 761_000]
    assert body["tresorerie"] is None and body["paiements"] is None and body["campagnes"] is None


def test_diocese_parishes_are_never_sorted_by_amount(world, sept):
    big = make_node("paroisse", "Paroisse Aa (plus gros montant)", world.tree.doyenne, code="T-AA")
    small = make_node("paroisse", "Paroisse Zz", world.tree.doyenne, code="T-ZZ")
    for parish, amount in [(big, 900_000), (small, 1_000)]:
        DonationActivation.objects.create(node=parish, enabled=True)
        fund = Fund.objects.create(node=parish, kind=FundKind.QUETE_DOMINICALE, title="Quête",
                                   destination=FundDestination.PAROISSE, status=FundStatus.OUVERT)  # fmt: skip
        Donation.objects.create(reference=f"R-{parish.code}", fund=fund, amount=amount, charged_amount=amount,
                                net_amount=amount, channel=DonationChannel.EN_LIGNE, status=DonationStatus.CONFIRME,
                                value_date=datetime.date(2026, 9, 10))  # fmt: skip
    names = [p["nom"] for p in analyse(world.eveque, world.dakar, "diocese").json()["paroisses"]["lignes"]]
    assert names == sorted(names, key=selectors_analyse.alpha_key)
    assert names.index("Paroisse Aa (plus gros montant)") < names.index("Paroisse Zz")


def test_doyenne_scope_and_access_rules(world, sept):
    assert analyse(world.econome_dio, world.tree.doyenne, "diocese").status_code == 200
    assert analyse(world.econome_dio, world.sd).status_code == 403  # pas de nomination sur la paroisse
    assert analyse(world.cure, world.dakar, "diocese").status_code == 403
    assert analyse(world.doyen, world.tree.doyenne, "diocese").status_code == 403  # pas de voir_agregats
    assert analyse(world.platform, world.dakar, "diocese").status_code == 403  # plateforme : aucun montant
    assert analyse(world.econome_dio, world.thies, "diocese").status_code == 403
    assert analyse(world.econome_dio, world.sd, "diocese").status_code == 400  # une paroisse n'est pas un agrégat
    assert analyse(world.econome_dio, world.dakar, "diocese", periode="semaine", date="2026-W39").status_code == 400
    assert analyse(world.fidele, world.sd).status_code == 403
    assert analyse(world.cure, world.sd, date="2026-13").status_code == 400


def test_other_periods(world, sept):
    week = analyse(world.cure, world.sd, periode="semaine", date="2026-W39").json()
    assert week["tendance"]["grain"] == "jour" and len(week["tendance"]["points"]) == 7
    assert week["synthese"]["collecte"] == 761_275
    quarter = analyse(world.cure, world.sd, periode="trimestre", date="2026-T3").json()
    assert quarter["periode"]["debut"] == "2026-07-01" and quarter["tendance"]["grain"] == "mois"
    assert [p["libelle"] for p in quarter["tendance"]["points"]] == ["juillet", "août", "septembre"]
    year = analyse(world.econome_dio, world.dakar, "diocese", periode="annee", date="2026").json()
    assert year["synthese"]["collecte"] == 2_165_000  # 1 214 830 + 950 000 de la campagne avant septembre


@pytest.mark.parametrize(
    "kind, code, start, end",
    [
        ("mois", "2026-02", datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)),
        ("trimestre", "2026-T4", datetime.date(2026, 10, 1), datetime.date(2026, 12, 31)),
        ("annee", "2027", datetime.date(2027, 1, 1), datetime.date(2027, 12, 31)),
        ("semaine", "2026-W39", datetime.date(2026, 9, 21), datetime.date(2026, 9, 27)),
    ],
)
def test_period_parse(kind, code, start, end):
    period = selectors_analyse.period_parse(kind, code)
    assert (period.start, period.end) == (start, end)
    assert period.shifted(-1).end < period.start


@pytest.mark.parametrize("kind, code", [("mois", "2026-9"), ("trimestre", "2026-T5"), ("semaine", "2026-W60"), ("x", "")])
def test_period_parse_errors(kind, code):
    with pytest.raises(ApplicationError):
        selectors_analyse.period_parse(kind, code)


def test_evolution_compares_a_parish_with_itself_after_three_full_periods(world, sept):
    DonationActivation.objects.filter(node=world.sd).update(authorization_date=datetime.date(2026, 6, 1))
    row = analyse(world.econome_dio, world.dakar, "diocese").json()["paroisses"]["lignes"][2]
    assert row["nom"] == "Saint-Dominique" and row["evolution"] == "en_hausse"
    DonationActivation.objects.filter(node=world.sd).update(authorization_date=datetime.date(2026, 6, 2))
    row = analyse(world.econome_dio, world.dakar, "diocese").json()["paroisses"]["lignes"][2]
    assert row["evolution"] is None
