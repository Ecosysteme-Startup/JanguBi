"""Semeur des personnes (``seed_realiste``, lot S1) : fidèles sans compte Keycloak (seules les personas de
``seed_demo`` se connectent), noms locaux, pyramide des âges jeune, quelques mineurs, présence variée."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.core.seeding import names
from apps.core.seeding.context import DOMAIN, SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register

# Pyramide : 60 % de moins de 35 ans (dont ~6 % de mineurs, règle RG-13 de la messagerie).
AGE_BANDS = [((12, 17), 6), ((18, 24), 22), ((25, 34), 32), ((35, 49), 22), ((50, 64), 12), ((65, 85), 6)]


def _age(rng: Any) -> int:
    (lo, hi) = rng.choices([b for b, _ in AGE_BANDS], [w for _, w in AGE_BANDS])[0]
    return rng.randint(lo, hi)


def _last_seen(rng: Any, ctx: SeedContext) -> datetime.datetime | None:
    r = rng.random()
    if r < 0.40:
        delta = datetime.timedelta(minutes=rng.randint(1, 7 * 24 * 60))
    elif r < 0.70:
        delta = datetime.timedelta(days=rng.randint(7, 30))
    elif r < 0.90:
        delta = datetime.timedelta(days=rng.randint(30, 90))
    elif r < 0.97:
        delta = datetime.timedelta(days=rng.randint(90, 360))
    else:
        return None
    return ctx.now - delta


@register
class PersonnesSeeder(Seeder):
    name = "personnes"
    module = "socle"
    phase = Phase.PERSONNES
    depends = ("hierarchie",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.users.models import BaseUser, Profile

        rng = ctx.rng(self.name)
        users: list[Any] = []
        profiles: list[Any] = []
        minors = 0
        for i in range(ctx.scale.fideles):
            first, last, sex = names.person(rng)
            age = _age(rng)
            minors += age < 18
            birth = ctx.today.replace(year=ctx.today.year - age) - datetime.timedelta(days=rng.randint(1, 360))
            seen = _last_seen(rng, ctx)
            user = BaseUser(
                id=uuid.UUID(int=rng.getrandbits(128), version=4),
                email=f"{names.slug(first)}.{names.slug(last)}.{i + 1:05d}@{DOMAIN}",
                password="!seed", is_active=True, is_verified=True, etat_de_vie="laic", degre_ordre="aucun",
                statut_verification="verifie", consent_version=settings.CONSENT_CURRENT_VERSION,
                consent_at=ctx.now - datetime.timedelta(days=rng.randint(1, 400)),
                last_seen_at=seen, last_seen_on=seen.date() if seen else None,
                # Présence : défaut (None) pour la plupart, masquage explicite pour quelques-uns.
                montrer_presence=rng.choices([None, True, False], [80, 12, 8])[0],
            )  # fmt: skip
            user.created_at = ctx.now - datetime.timedelta(days=rng.randint(30, 900))
            users.append(user)
            profiles.append(
                Profile(user=user, first_name=first, last_name=last, date_of_birth=birth,
                        title="MRS" if sex == "F" else "MR")
            )  # fmt: skip
        with transaction.atomic():
            BaseUser.objects.bulk_create(users, batch_size=2000)
            Profile.objects.bulk_create(profiles, batch_size=2000)
            ctx.track(BaseUser, [u.pk for u in users])
        return {"fideles": len(users), "mineurs": minors}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.users.models import BaseUser

        ids = ctx.tracked_ids(BaseUser)  # fidèles et staff du lot
        total = 0
        for start in range(0, len(ids), 5000):
            n, _ = BaseUser.objects.filter(pk__in=ids[start : start + 5000]).delete()
            total += n
        return {"objets": total}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.users.models import BaseUser

        qs = BaseUser.objects.filter(pk__in=ctx.tracked_ids(BaseUser))
        outside = qs.exclude(email__endswith=f"@{DOMAIN}").count()
        return [Check(f"Adresses en @{DOMAIN} uniquement", outside == 0, f"{qs.count()} comptes, {outside} hors domaine")]


@register
class ComptesKeycloakSeeder(Seeder):
    """Recette : comptes Keycloak des personas de ``seed_demo`` par l'API d'administration, avec le mot de
    passe de recette commun ``KC_DEMO_PASSWORD`` (docs/RECETTE.md). Les autres fidèles n'ont pas de compte.
    Hors recette, ou sans administration Keycloak configurée : étape sautée et signalée, jamais bloquante."""

    name = "comptes_keycloak"
    module = "socle"
    phase = Phase.PERSONNES
    depends = ("hierarchie",)
    always = True

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        import os

        if ctx.profil != "recette":
            return {"comptes": "profil local : non créés (scripts infra/keycloak/seed-demo-users.sh)"}
        password = os.environ.get("KC_DEMO_PASSWORD", "")
        if not ctx.reseau or not password or not getattr(settings, "KEYCLOAK_ADMIN_CLIENT_SECRET", ""):
            ctx.note("Comptes Keycloak des personas non créés : KC_DEMO_PASSWORD ou KEYCLOAK_ADMIN_CLIENT_SECRET absent.")
            return {"comptes": "sautés"}
        from apps.authentication.keycloak_admin import KeycloakAdmin
        from apps.core.management.commands.seed_demo import PEOPLE

        admin = KeycloakAdmin()
        created = existing = 0
        try:
            for key, first, last, *_ in PEOPLE:
                _, was_created = admin.user_create({
                    "username": f"{key}@{DOMAIN}", "email": f"{key}@{DOMAIN}", "emailVerified": True, "enabled": True,
                    "firstName": first, "lastName": last,
                    "credentials": [{"type": "password", "value": password, "temporary": False}],
                })  # fmt: skip
                created += was_created
                existing += not was_created
            platform_id = admin.user_id_by_email(f"plateforme@{DOMAIN}")
            if platform_id:
                admin.add_realm_role(platform_id, "platform_admin")
        except Exception as exc:  # noqa: BLE001 - Keycloak injoignable : signalé, jamais bloquant
            ctx.note(f"Keycloak : {exc}")
        return {"crees": created, "existants": existing}
