"""Données de démonstration V1 sur la paroisse pilote (profil « senegal »). Idempotent.

Prérequis : ``manage.py seed_hierarchy_profile senegal``. Les comptes créés n'ont pas de mot
de passe : ils se connectent par Keycloak avec la même adresse (e-mail vérifié), qui les
rattache à la personne existante (ADR-015). ``--reset`` retire tout ce qui a été créé.
"""

import datetime
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

DOMAIN = "demo.jangubi.sn"
PEOPLE = [
    # (clé, prénom, nom, état de vie, degré d'ordre, date de naissance)
    ("cure", "Joseph", "Sarr", "clerc", "pretre", datetime.date(1970, 3, 19)),
    ("vicaire", "Paul", "Diouf", "clerc", "pretre", datetime.date(1985, 6, 29)),
    ("secretaire", "Marie", "Faye", "laic", "aucun", datetime.date(1980, 8, 15)),
    ("doyen", "Augustin", "Ndiaye", "clerc", "pretre", datetime.date(1965, 8, 28)),
    ("fidele", "Awa", "Diop", "laic", "aucun", datetime.date(1995, 3, 4)),
    ("fidele2", "Moussa", "Mendy", "laic", "aucun", datetime.date(1990, 11, 1)),
    # Mineur : la messagerie lui est refusée (RG-13), avec explication.
    ("mineur", "Fatou", "Sène", "laic", "aucun", datetime.date(2012, 5, 10)),
    ("chancelier", "Théodore", "Diatta", "clerc", "pretre", datetime.date(1968, 1, 25)),
    # Administrateur paroissial (qualité de l'office « cure ») d'une seconde paroisse de démonstration.
    ("admin_paroissial", "Robert", "Sagna", "clerc", "pretre", datetime.date(1978, 10, 4)),
    # Administrateur plateforme : rôle de realm Keycloak `platform_admin`, aucune nomination.
    ("plateforme", "Mariama", "Ba", "laic", "aucun", datetime.date(1988, 2, 14)),
    # Dons et quêtes (ADR-017) : économe de la paroisse pilote et économe diocésain.
    ("econome", "Anne", "Mendy", "laic", "aucun", datetime.date(1983, 4, 12)),
    ("econome_dio", "Bernard", "Coly", "laic", "aucun", datetime.date(1972, 7, 3)),
]
# (personne, office, où, qualité)
OFFICES = [("cure", "cure", "parish", "cure"), ("vicaire", "vicaire_paroissial", "parish", ""),
           ("secretaire", "secretaire_paroissial", "parish", ""), ("doyen", "doyen", "deanery", ""),
           ("chancelier", "chancelier", "diocese", ""),
           ("admin_paroissial", "cure", "parish2", "administrateur"),
           ("econome", "econome_paroissial", "parish", ""), ("econome_dio", "econome_diocesain", "diocese", "")]  # fmt: skip
SECOND_PARISH_CODE = "DEMO-STE-THERESE"


class Command(BaseCommand):
    help = "Données de démonstration V1 sur la paroisse pilote Saint-Dominique (idempotent)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--reset", action="store_true", help="Supprime les données de démonstration.")

    def handle(self, *args: Any, reset: bool = False, **options: Any) -> None:
        if reset:
            self._reset()
            return
        from apps.hierarchy.models import Node
        from apps.hierarchy.profiles import PILOT_PARISH_CODE

        parish = Node.objects.filter(code=PILOT_PARISH_CODE).first()
        if parish is None:
            raise CommandError("Paroisse pilote absente : lancez d'abord seed_hierarchy_profile senegal.")
        with transaction.atomic():
            people = self._people(parish)
            self._memberships(people, parish)
            self._offices(people, parish)
            self._content(people, parish)
            self._donations(people, parish)
        self.stdout.write(self.style.SUCCESS(f"Démo prête : comptes *@{DOMAIN} (connexion par Keycloak)."))

    def _people(self, parish: Any) -> dict[str, Any]:
        from apps.users.models import BaseUser, Profile

        people = {}
        for key, first, last, etat, degre, birth in PEOPLE:
            user, _ = BaseUser.objects.get_or_create(
                email=f"{key}@{DOMAIN}",
                defaults={
                    "is_active": True,
                    "is_verified": True,
                    "etat_de_vie": etat,
                    "degre_ordre": degre,
                    "statut_verification": "verifie",
                    "paroisse_suivie": parish,
                    "consent_version": settings.CONSENT_CURRENT_VERSION,
                    "consent_at": timezone.now(),
                },
            )
            if not user.has_usable_password():
                user.set_unusable_password()
            Profile.objects.update_or_create(
                user=user, defaults={"first_name": first, "last_name": last, "date_of_birth": birth}
            )
            people[key] = user
        return people

    def _offices(self, people: dict[str, Any], parish: Any) -> None:
        from apps.hierarchy import authz
        from apps.hierarchy.models import OfficeAssignment, OfficeType

        deanery = parish.get_parent()
        diocese = next(n for n in reversed(parish.get_ancestors()) if n.type.code == "diocese")
        nodes = {"parish": parish, "deanery": deanery, "diocese": diocese, "parish2": self._second_parish(deanery)}
        for key, office_code, where, quality in OFFICES:
            OfficeAssignment.objects.get_or_create(
                person=people[key],
                office_type=OfficeType.objects.get(code=office_code),
                node=nodes[where],
                defaults={
                    "start_date": datetime.date(2024, 9, 1),
                    "status": "active",
                    "note": "Démonstration",
                    "quality": quality,
                },
            )
            authz.invalidate_user(people[key].pk)

    def _memberships(self, people: dict[str, Any], parish: Any) -> None:
        """Paroisses multiples (décisions 6-8) : la paroisse pilote est la principale de chacun ;
        la fidèle de démo suit aussi Sainte-Thérèse de Grand-Dakar en paroisse secondaire."""
        from apps.hierarchy.services_memberships import membership_join

        for user in people.values():
            if user.paroisse_suivie_id:
                membership_join(user=user, node=user.paroisse_suivie)
        membership_join(user=people["fidele"], node=self._second_parish(parish.get_parent()))

    def _second_parish(self, deanery: Any) -> Any:
        from apps.hierarchy.models import Node, NodeType
        from apps.hierarchy.services import node_create

        existing = Node.objects.filter(code=SECOND_PARISH_CODE).first()
        if existing is not None:
            return existing
        return node_create(
            node_type=NodeType.objects.get(code="paroisse"),
            name="Sainte-Thérèse de Grand-Dakar",
            parent=deanery,
            code=SECOND_PARISH_CODE,
            city="Dakar",
            address="Grand-Dakar",
            is_active_on_platform=True,
        )

    def _content(self, people: dict[str, Any], parish: Any) -> None:
        from apps.agenda.models import Event
        from apps.agenda.services import event_create
        from apps.confessions.models import ConfessionSlotRule
        from apps.confessions.services import rule_create
        from apps.documents.models import DocumentRequest
        from apps.documents.services import document_request_create
        from apps.news.models import Article, ArticleCategory
        from apps.news.services import article_create, article_publish

        place = parish.places.filter(is_main=True).first()
        category, _ = ArticleCategory.objects.get_or_create(slug="vie-paroissiale", defaults={"name": "Vie paroissiale"})
        cure, vicaire = people["cure"], people["vicaire"]
        now = timezone.now()
        today = timezone.localdate()
        next_sunday = today + datetime.timedelta(days=(6 - today.weekday()) % 7)
        if not Article.objects.filter(author=cure).exists():
            for title, content_type, sunday in [
                ("Annonces du dimanche", Article.ContentType.ANNOUNCEMENT, True),
                ("Méditation : la foi comme une graine de moutarde", Article.ContentType.MEDITATION, False),
                ("Inscriptions au catéchisme", Article.ContentType.ARTICLE, False),
            ]:
                article = article_create(
                    author=cure,
                    title=title,
                    content="Texte de démonstration.",
                    category=category,
                    node=parish,
                    content_type=content_type,
                    is_sunday_notice=sunday,
                    sunday_date=next_sunday if sunday else None,
                )
                article_publish(article=article, editor=cure)
        if not Event.objects.filter(organizer=cure).exists():
            start = now + datetime.timedelta(days=10)
            event_create(
                organizer=cure,
                title="Veillée de prière",
                start_at=start,
                end_at=start + datetime.timedelta(hours=2),
                node=parish,
                place=place,
                max_participants=80,
            )
        if place and not ConfessionSlotRule.objects.filter(priest=vicaire).exists():
            rule_create(
                priest=vicaire,
                place=place,
                weekday=5,
                start_time=datetime.time(10, 0),
                end_time=datetime.time(11, 0),
                slot_minutes=15,
            )
        if not DocumentRequest.objects.filter(requester=people["fidele"]).exists():
            document_request_create(
                requester=people["fidele"],
                target_node=parish,
                data={
                    "document_type": "baptism",
                    "reason": "religious_marriage",
                    "requester_last_name": "Diop",
                    "requester_first_names": "Awa",
                    "date_of_birth": datetime.date(1995, 3, 4),
                    "place_of_birth": "Dakar",
                    "contact_phone": "+221770000001",
                    "contact_email": f"fidele@{DOMAIN}",
                    "father_last_name": "Diop",
                    "mother_last_name": "Sow",
                    "sacrament_approximate_date": "1995",
                    "sacrament_location": "Saint-Dominique",
                    "consent_given": True,
                },
            )

    def _donations(self, people: dict[str, Any], parish: Any) -> None:
        """Pilote Saint-Dominique : collecte activée, fonds du 27 septembre 2026, quête impérée de Brin."""
        from apps.donations import services as dons
        from apps.donations.models import DonationActivation, Fund

        DonationActivation.objects.update_or_create(
            node=parish,
            defaults={
                "enabled": True,
                "authorization_ref": "DEMO-ARCH-DAK-2026",
                "authorization_date": datetime.date(2026, 9, 1),
                "authorization_text": "Collecte autorisée par l'Archevêché de Dakar (démonstration).",
                "allocation_key": "DEMO-SD",
                "receipt_prefix": "SD",
            },
        )
        cure = people["cure"]
        if Fund.objects.filter(node=parish, decided_by=cure).exists():
            return
        funds = [
            ("quete_dominicale", "Quête du dimanche 27 septembre", "Vie de la paroisse et entretien des lieux.",
             datetime.date(2026, 9, 27), datetime.date(2026, 10, 4), None),
            ("campagne", "Toiture de la chapelle de la Cité universitaire",
             "Remplacement des tôles et de la charpente avant l'hivernage.", datetime.date(2026, 9, 1),
             datetime.date(2026, 12, 31), 4_500_000),
            ("contribution_annuelle", "Contribution annuelle 2026", "Participation des fidèles à la vie de l'Église.",
             datetime.date(2026, 1, 1), datetime.date(2026, 12, 31), None),
        ]  # fmt: skip
        for kind, title, description, starts_on, ends_on, goal in funds:
            fund = dons.fund_create(
                actor=cure, node=parish, kind=kind, title=title, description=description,
                starts_on=starts_on, ends_on=ends_on, goal_amount=goal,
            )  # fmt: skip
            dons.fund_publish(fund=fund, actor=cure)
        diocese = next(n for n in reversed(parish.get_ancestors()) if n.type.code == "diocese")
        if not Fund.objects.filter(node=diocese, kind="quete_imperee").exists():
            dons.imperee_create(
                actor=people["econome_dio"],
                diocese=diocese,
                title="Quête impérée pour le Grand Séminaire de Brin",
                description="Formation des séminaristes (reversée à la curie).",
                starts_on=datetime.date(2026, 9, 27),
                ends_on=datetime.date(2026, 10, 4),
                parishes=[parish],
                authorization_ref="DEMO-ARCH-DAK-2026",
            )

    def _reset(self) -> None:
        from apps.agenda.models import Event
        from apps.confessions.models import ConfessionSlot, ConfessionSlotRule
        from apps.documents.models import DocumentRequest
        from apps.hierarchy.models import Node, OfficeAssignment
        from apps.news.models import Article
        from apps.users.models import BaseUser

        with transaction.atomic():
            people = BaseUser.objects.filter(email__endswith=f"@{DOMAIN}")
            ConfessionSlot.objects.filter(priest__in=people).delete()
            ConfessionSlotRule.objects.filter(priest__in=people).delete()
            Event.objects.filter(organizer__in=people).delete()
            Article.objects.filter(author__in=people).delete()
            DocumentRequest.objects.filter(requester__in=people).delete()
            from apps.donations.models import CashCollection, Donation, DonationActivation, Fund

            demo_funds = Fund.objects.filter(decided_by__in=people)
            Donation.objects.filter(fund__in=demo_funds).delete()
            CashCollection.objects.filter(fund__in=demo_funds).delete()
            Fund.objects.filter(parent__in=demo_funds).delete()
            demo_funds.delete()
            DonationActivation.objects.filter(authorization_ref="DEMO-ARCH-DAK-2026").delete()
            OfficeAssignment.objects.filter(person__in=people).delete()
            Node.objects.filter(code=SECOND_PARISH_CODE).delete()
            count = people.count()
            people.delete()
        self.stdout.write(self.style.SUCCESS(f"{count} compte(s) de démonstration supprimé(s)."))
