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
]
# (personne, office, où, qualité)
OFFICES = [("cure", "cure", "parish", "cure"), ("vicaire", "vicaire_paroissial", "parish", ""),
           ("secretaire", "secretaire_paroissial", "parish", ""), ("doyen", "doyen", "deanery", ""),
           ("chancelier", "chancelier", "diocese", ""),
           ("admin_paroissial", "cure", "parish2", "administrateur")]  # fmt: skip
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
            self._offices(people, parish)
            self._content(people, parish)
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
            OfficeAssignment.objects.filter(person__in=people).delete()
            Node.objects.filter(code=SECOND_PARISH_CODE).delete()
            count = people.count()
            people.delete()
        self.stdout.write(self.style.SUCCESS(f"{count} compte(s) de démonstration supprimé(s)."))
