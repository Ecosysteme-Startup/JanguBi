"""Catalogue des e-mails envoyés par le backend, avec un contexte d'exemple pour chacun.

Sert à la commande ``apercu_emails`` (relecture) et aux tests de rendu : tout nouvel e-mail
s'ajoute ici, sinon ``test_catalogue_couvre_tous_les_gabarits`` échoue.
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.documents.models import DocumentRequest
from apps.documents.services import ORIGINAL_NOTICE, _REQUESTER_MESSAGES, _REQUESTER_TITLES


@dataclass(frozen=True)
class EmailSpec:
    nom: str
    template: str
    description: str
    contexte: Callable[[], dict[str, Any]]


def _dans(jours: int, heure: int, minute: int = 0) -> datetime.datetime:
    base = timezone.localtime() + datetime.timedelta(days=jours)
    return base.replace(hour=heure, minute=minute, second=0, microsecond=0)


def _web() -> str:
    return str(getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")


def _statut(statut: str, complement: str = "") -> dict[str, Any]:
    reference, paroisse = "ACT-2026-00412", "Paroisse Saint-Dominique"
    return {
        "titre": _REQUESTER_TITLES[statut],
        "message": _REQUESTER_MESSAGES[statut].format(ref=reference, parish=paroisse),
        "complement": complement,
        "original": ORIGINAL_NOTICE if statut == DocumentRequest.Status.READY_FOR_PICKUP else "",
        "prenoms": "Awa Marie",
        "reference": reference,
        "paroisse": paroisse,
    }


def _presentation() -> dict[str, Any]:
    demande = SimpleNamespace(
        full_name="Abbé Jean Diouf",
        get_fonction_display=lambda: "Curé",
        paroisse="Paroisse Sainte-Thérèse de Grand-Dakar",
        diocese_node=SimpleNamespace(name="Archidiocèse de Dakar"),
        telephone="+221 77 123 45 67",
        email="paroisse.stetherese@example.sn",
        cure_informe=True,
        message="Bonjour,\nNous aimerions présenter Jàngu Bi au conseil pastoral le mois prochain.",
        consented_at=timezone.localtime() - datetime.timedelta(hours=2),
    )
    return {"request": demande}


def _invitation() -> dict[str, Any]:
    invitation = SimpleNamespace(
        first_name="Pierre",
        node=SimpleNamespace(name="Paroisse Saint-Dominique"),
        expires_at=timezone.localtime() + datetime.timedelta(days=14),
    )
    return {
        "invitation": invitation,
        "accept_url": f"{_web()}/accept-invitation?token=exemple",
        "register_url": "https://accounts.example.sn/realms/jangubi/protocol/openid-connect/registrations?login_hint=exemple",
    }


CATALOGUE: list[EmailSpec] = [
    EmailSpec(
        "annonce_publiee",
        "notifications/annonce_publiee",
        "Nouvelle annonce d'une paroisse suivie",
        lambda: {
            "title": "Fête paroissiale de la Saint-Dominique",
            "node_name": "Paroisse Saint-Dominique",
            "paroisse": "Paroisse Saint-Dominique",
            "article_id": "3f1c6a2e-0000-4000-8000-000000000001",
        },
    ),
    EmailSpec(
        "evenement_rappel",
        "notifications/evenement_rappel",
        "Rappel d'un événement auquel la personne est inscrite",
        lambda: {
            "title": "Retraite de l'Avent des jeunes",
            "start_at": _dans(2, 9, 30),
            "location": "Centre Saint-Augustin, Dakar",
            "event_id": 42,
            "paroisse": "Paroisse Saint-Dominique",
        },
    ),
    EmailSpec(
        "evenement_annule",
        "agenda/evenement_annule",
        "Annulation d'un événement (à chaque inscrit)",
        lambda: {
            "title": "Retraite de l'Avent des jeunes",
            "start_at": _dans(2, 9, 30),
            "paroisse": "Paroisse Saint-Dominique",
        },
    ),
    EmailSpec(
        "rendez_vous_rappel",
        "notifications/confession_rappel",
        "Rappel de rendez-vous avec un prêtre (J-1 et H-2)",
        lambda: {"starts_at": _dans(1, 17, 0), "place": "Église Saint-Dominique"},
    ),
    EmailSpec(
        "rendez_vous_annule",
        "notifications/confession_annulation",
        "Rendez-vous annulé par le prêtre",
        lambda: {
            "starts_at": _dans(1, 17, 0),
            "place": "Église Saint-Dominique",
            "message": "Je dois m'absenter pour une célébration. Merci de reprendre un créneau samedi prochain.",
        },
    ),
    EmailSpec(
        "don_recu",
        "donations/recu_don",
        "Reçu simple d'un don fait sans compte",
        lambda: {
            "recu_numero": "R-2026-000187",
            "reference": "DON-7K2P9Q",
            "fonds": "Construction de la chapelle de Keur Massar",
            "paroisse": "Paroisse Saint-Dominique",
            "montant": 25000,
            "date": timezone.localtime(),
        },
    ),
    EmailSpec(
        "acte_transmise",
        "documents/demande_statut",
        "Demande d'acte transmise à la paroisse",
        lambda: _statut(DocumentRequest.Status.SUBMITTED),
    ),
    EmailSpec(
        "acte_complement",
        "documents/demande_statut",
        "Demande d'acte : la paroisse demande un complément",
        lambda: _statut(DocumentRequest.Status.INFO_REQUESTED, "Merci de préciser la date approximative du baptême."),
    ),
    EmailSpec(
        "acte_pret",
        "documents/demande_statut",
        "Demande d'acte : l'original est prêt à retirer",
        lambda: _statut(DocumentRequest.Status.READY_FOR_PICKUP),
    ),
    EmailSpec(
        "acte_refusee",
        "documents/demande_statut",
        "Demande d'acte : la demande n'a pas pu aboutir",
        lambda: _statut(
            DocumentRequest.Status.REJECTED, "Aucun registre ne correspond aux informations données pour cette année."
        ),
    ),
    EmailSpec(
        "invitation_clerge",
        "invitations/invitation_clerge",
        "Invitation d'un membre du clergé",
        _invitation,
    ),
    EmailSpec(
        "declaration_complement",
        "hierarchy/complement_declaration",
        "La chancellerie demande un complément de déclaration",
        dict,
    ),
    EmailSpec(
        "presentation_demande",
        "contact/presentation_request",
        "Formulaire « Pour les paroisses » (message interne)",
        _presentation,
    ),
]
