"""Semeurs de la hiérarchie (``seed_realiste``, lot S1) : paroisses peuplées, lieux et horaires,
appartenances des fidèles, staff des paroisses (curé, vicaires, secrétaire, économe) et présence."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.db.models import Count, Q

from apps.core.seeding import names
from apps.core.seeding.context import DOMAIN, SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.core.seeding.world import EXTRA_PARISHES, SEED_PARISH_PREFIX

# Horaires types d'une paroisse de Dakar : messe anticipée le samedi soir, trois ou quatre le dimanche.
SUNDAY_TIMES = [datetime.time(7, 0), datetime.time(9, 30), datetime.time(11, 30), datetime.time(18, 30)]
SATURDAY_EVENING = datetime.time(18, 30)


def staff_of(node: Any, office_code: str) -> Any:
    """Titulaire actif d'un office sur une paroisse (personas comprises)."""
    from apps.hierarchy.models import OfficeAssignment

    a = (
        OfficeAssignment.objects.filter(node=node, office_type__code=office_code, status="active")
        .select_related("person")
        .order_by("start_date", "created_at")
        .first()
    )
    return a.person if a else None


@register
class HierarchieSeeder(Seeder):
    name = "hierarchie"
    module = "socle"
    phase = Phase.HIERARCHIE

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship
        from apps.hierarchy.profiles import PILOT_PARISH_CODE
        from apps.hierarchy.services import node_create

        if not Node.objects.filter(code=PILOT_PARISH_CODE).exists():
            ctx.log("référentiel absent : seed_hierarchy_profile senegal")
            call_command("seed_hierarchy_profile", "senegal", verbosity=0)
        if not Node.objects.filter(code="DEMO-STE-THERESE").exists() or ctx.persona("cure") is None:
            ctx.log("personas absentes : seed_demo")
            call_command("seed_demo", verbosity=0)
        rng = ctx.rng(self.name)
        parish_type = NodeType.objects.get(code="paroisse")
        deaneries = list(Node.objects.filter(type__code="doyenne", code__startswith="DAK-D-").order_by("code"))
        created_nodes, created_places = [], []
        codes = [c for c in _codes(ctx) if c.startswith(SEED_PARISH_PREFIX)]
        with transaction.atomic():
            for i, code in enumerate(codes):
                if Node.objects.filter(code=code).exists():
                    continue
                name, quarter, chapels = EXTRA_PARISHES[i % len(EXTRA_PARISHES)]
                node = node_create(
                    node_type=parish_type, name=name, parent=deaneries[i % len(deaneries)], code=code,
                    city="Dakar", address=quarter, is_active_on_platform=True,
                )  # fmt: skip
                created_nodes.append(node.pk)
                church = PlaceOfWorship.objects.create(
                    node=node, name=f"Église {name.removeprefix('Paroisse ')}", kind="eglise_paroissiale",
                    is_main=True, city="Dakar", address=quarter,
                )  # fmt: skip
                created_places.append(church.pk)
                for chapel in chapels:
                    created_places.append(
                        PlaceOfWorship.objects.create(node=node, name=chapel, kind="chapelle", city="Dakar").pk
                    )
            # La seconde paroisse de démonstration n'a ni lieu ni horaire : on lui en donne.
            second = Node.objects.get(code="DEMO-STE-THERESE")
            if not second.places.exists():
                created_places.append(
                    PlaceOfWorship.objects.create(
                        node=second, name="Église Sainte-Thérèse", kind="eglise_paroissiale", is_main=True, city="Dakar"
                    ).pk
                )
            for place in PlaceOfWorship.objects.filter(pk__in=created_places):
                times = SUNDAY_TIMES if place.is_main else [rng.choice([datetime.time(8, 0), datetime.time(10, 0)])]
                if place.is_main and rng.random() < 0.4:
                    times = [t for t in times if t != datetime.time(18, 30)]
                for t in times:
                    MassSchedule.objects.create(place=place, kind="messe", weekday=6, start_time=t)
                if place.is_main:
                    MassSchedule.objects.create(place=place, kind="messe", weekday=5, start_time=SATURDAY_EVENING)
                    for wd in range(5):
                        MassSchedule.objects.create(
                            place=place, kind="messe", weekday=wd, start_time=datetime.time(7, 0)
                        )
                    MassSchedule.objects.create(
                        place=place, kind="confession", weekday=5, start_time=datetime.time(16, 0),
                        end_time=datetime.time(18, 0),
                    )  # fmt: skip
            ctx.track(Node, created_nodes)
            ctx.track(PlaceOfWorship, created_places)
        return {
            "paroisses": len(ctx.parishes()),
            "nouvelles_paroisses": len(created_nodes),
            "lieux": len(created_places),
        }

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy.models import Node, PlaceOfWorship

        places = ctx.tracked(PlaceOfWorship)
        n_places = places.count()
        places.delete()
        nodes = ctx.tracked(Node)
        n_nodes = nodes.count()
        for node in nodes:
            node.delete()
        return {"lieux": n_places, "paroisses": n_nodes}


def _codes(ctx: SeedContext) -> list[str]:
    from apps.core.seeding.world import parish_codes

    return parish_codes(ctx)


# Offices du staff d'une paroisse peuplée : (office, état de vie, degré, nombre)
STAFF = [
    ("cure", "clerc", "pretre", 1),
    ("vicaire_paroissial", "clerc", "pretre", 2),
    ("secretaire_paroissial", "laic", "aucun", 1),
    ("econome_paroissial", "laic", "aucun", 1),
]


@register
class AppartenancesSeeder(Seeder):
    """Une principale par fidèle, 20 % avec une ou deux secondaires, quelques retraits par la paroisse ;
    staff des paroisses sans personas ; réglages de présence variés."""

    name = "appartenances"
    module = "socle"
    phase = Phase.APPARTENANCES
    depends = ("hierarchie", "personnes")

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy import authz
        from apps.hierarchy.models import OfficeAssignment, OfficeType, ParishMembership
        from apps.users.models import BaseUser, Profile

        rng = ctx.rng(self.name)
        parishes = ctx.parishes()
        pilot = parishes[0]
        # Poids : la pilote est la plus peuplée ; les suivantes décroissent doucement.
        weights = [3.0] + [max(0.6, 1.6 - 0.05 * i) for i in range(len(parishes) - 1)]
        offices = {o.code: o for o in OfficeType.objects.filter(code__in=[s[0] for s in STAFF])}
        staff_users: list[Any] = []
        staff_profiles: list[Any] = []
        assignments: list[Any] = []
        n = 0
        with transaction.atomic():
            for parish in parishes:
                if parish.pk == pilot.pk:
                    continue  # personas de seed_demo
                for office_code, etat, degre, count in STAFF:
                    if staff_of(parish, office_code) is not None:
                        continue  # ex. l'administrateur paroissial de Sainte-Thérèse
                    for _ in range(count if office_code != "vicaire_paroissial" else rng.choice([1, 2])):
                        n += 1
                        first, last, sex = names.person(rng, "M" if etat == "clerc" else None)
                        user = BaseUser(
                            id=uuid.UUID(int=rng.getrandbits(128), version=4),
                            email=f"staff.{names.slug(first)}.{names.slug(last)}.{parish.code.lower()}.{n}@{DOMAIN}",
                            password="!seed", is_active=True, is_verified=True, etat_de_vie=etat, degre_ordre=degre,
                            statut_verification="verifie", paroisse_suivie=parish,
                            consent_version=settings.CONSENT_CURRENT_VERSION, consent_at=ctx.now,
                            last_seen_at=ctx.now - datetime.timedelta(hours=rng.randint(1, 72)),
                            last_seen_on=ctx.today - datetime.timedelta(days=rng.randint(0, 3)),
                            montrer_presence=rng.choice([None, None, True, False]),
                        )  # fmt: skip
                        staff_users.append(user)
                        birth_year = ctx.today.year - rng.randint(32, 68)
                        staff_profiles.append(
                            Profile(user=user, first_name=first, last_name=last,
                                    date_of_birth=datetime.date(birth_year, rng.randint(1, 12), rng.randint(1, 28)))
                        )  # fmt: skip
                        assignments.append(
                            OfficeAssignment(
                                person=user, office_type=offices[office_code], node=parish,
                                start_date=ctx.today - datetime.timedelta(days=rng.randint(200, 2000)),
                                status="active", note="Données de test", quality="cure" if office_code == "cure" else "",
                            )
                        )  # fmt: skip
            BaseUser.objects.bulk_create(staff_users)
            Profile.objects.bulk_create(staff_profiles)
            OfficeAssignment.objects.bulk_create(assignments)
            ctx.track(BaseUser, [u.pk for u in staff_users])
            ctx.track(OfficeAssignment, [a.pk for a in assignments])

            # Appartenances des fidèles du lot.
            fideles = list(ctx.fideles_qs().order_by("pk").values_list("pk", flat=True))
            memberships: list[Any] = []
            primary_of: dict[Any, Any] = {}
            removed = 0
            for uid in fideles:
                primary = rng.choices(parishes, weights)[0]
                primary_of[uid] = primary.pk
                joined = ctx.now - datetime.timedelta(days=rng.randint(20, 900))
                memberships.append(ParishMembership(user_id=uid, node=primary, is_primary=True, joined_at=joined))
                if rng.random() < 0.20 and len(parishes) > 1:
                    others = [p for p in parishes if p.pk != primary.pk]
                    for other in rng.sample(others, k=min(len(others), rng.choice([1, 1, 2]))):
                        m = ParishMembership(
                            user_id=uid, node=other, is_primary=False,
                            joined_at=joined + datetime.timedelta(days=rng.randint(1, 200)),
                        )  # fmt: skip
                        if rng.random() < 0.04:  # retrait par la paroisse (secondaire seulement)
                            m.removed_by_parish_at = ctx.now - datetime.timedelta(days=rng.randint(2, 120))
                            m.removed_by = staff_of(other, "secretaire_paroissial")
                            removed += 1
                        memberships.append(m)
            ParishMembership.objects.bulk_create(memberships, batch_size=5000)
            by_parish: dict[Any, list[Any]] = {}
            for uid, pid in primary_of.items():
                by_parish.setdefault(pid, []).append(uid)
            for pid, uids in by_parish.items():
                BaseUser.objects.filter(pk__in=uids).update(paroisse_suivie_id=pid)
        for u in staff_users:
            authz.invalidate_user(u.pk)
        return {"staff": len(staff_users), "appartenances": len(memberships), "retraits": removed}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy.models import OfficeAssignment, ParishMembership
        from apps.users.models import BaseUser

        staff_ids = ctx.tracked_ids(BaseUser, self.name)
        OfficeAssignment.objects.filter(pk__in=ctx.tracked_ids(OfficeAssignment, self.name)).delete()
        n, _ = ParishMembership.objects.filter(user_id__in=ctx.tracked_ids(BaseUser, "personnes")).delete()
        ParishMembership.objects.filter(removed_by_id__in=staff_ids).update(removed_by=None)
        return {"appartenances": n, "staff": len(staff_ids)}  # comptes du staff supprimés par « personnes »

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.hierarchy.models import ParishMembership

        fideles = ctx.fideles_qs()
        total = fideles.count()
        bad = (
            fideles.annotate(
                n=Count("parish_memberships", filter=Q(parish_memberships__is_primary=True,
                                                       parish_memberships__removed_by_parish_at__isnull=True))
            )
            .exclude(n=1)
            .count()
        )  # fmt: skip
        mismatch = (
            ParishMembership.objects.filter(user__in=fideles, is_primary=True)
            .exclude(node_id=models_f("user__paroisse_suivie_id"))
            .count()
        )
        parishes = ctx.parishes()
        staffed = sum(1 for p in parishes if staff_of(p, "cure") and staff_of(p, "econome_paroissial"))
        return [
            Check("Une paroisse principale par fidèle", bad == 0 and total > 0, f"{total} fidèles, {bad} en écart"),
            Check("paroisse_suivie = principale", mismatch == 0, f"{mismatch} écart(s)"),
            Check(
                "Curé et économe dans chaque paroisse peuplée", staffed == len(parishes), f"{staffed}/{len(parishes)}"
            ),
        ]


def models_f(name: str) -> Any:
    from django.db.models import F

    return F(name)
