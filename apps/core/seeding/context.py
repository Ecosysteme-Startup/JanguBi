"""Contexte partagé d'un semis : graine, échelle, lot, traces, journal."""

from __future__ import annotations

import datetime
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.db import models
from django.utils import timezone

DOMAIN = "demo.jangubi.sn"  # même domaine que les personas de seed_demo (garde-fou : jamais une vraie adresse)
DEVICE_ID = "seed-realiste"  # marque les événements d'écoute et de lecture semés


@dataclass(frozen=True)
class Scale:
    code: str
    paroisses: int
    fideles: int
    dons: int
    pistes: int
    ecoutes: int
    # Volumes secondaires, proportionnés.
    articles_par_paroisse: int
    evenements_par_paroisse: int
    demandes_actes: int
    conversations: int
    lecteurs_parole: int


SCALES: dict[str, Scale] = {
    "petite": Scale("petite", 3, 300, 4_000, 40, 20_000, 8, 5, 30, 20, 120),
    "moyenne": Scale("moyenne", 12, 5_000, 80_000, 250, 600_000, 12, 8, 400, 200, 1_500),
    "grande": Scale("grande", 40, 50_000, 1_000_000, 1_500, 5_000_000, 16, 10, 3_000, 1_500, 12_000),
}

MEDIAS = ("complets", "legers", "aucun")


@dataclass
class SeedContext:
    profil: str
    scale: Scale
    graine: int
    medias: str = "legers"
    historique: int = 12
    medias_dossier: str | None = None
    bible_json: str | None = None
    bible_source: str = "AELF"
    piper_voix: str | None = None
    reseau: bool = True
    stdout: Any = None
    today: datetime.date = field(default_factory=timezone.localdate)
    now: datetime.datetime = field(default_factory=timezone.now)
    notes: list[str] = field(default_factory=list)
    current_seeder: str = ""
    _faker: Any = None

    @property
    def batch(self) -> str:
        return f"realiste-{self.graine}"

    # --- Hasard reproductible ------------------------------------------------------------------

    def rng(self, name: str) -> random.Random:
        """Un générateur par semeur, dérivé de la graine : un module rejoué seul donne les mêmes données."""
        return random.Random(f"{self.graine}:{name}")

    @property
    def faker(self) -> Any:
        if self._faker is None:
            from faker import Faker

            self._faker = Faker("fr_FR")
            self._faker.seed_instance(self.graine)
        return self._faker

    # --- Période ---------------------------------------------------------------------------------

    @property
    def start(self) -> datetime.date:
        """Premier jour de l'historique (premier jour du mois, ``historique`` mois en arrière)."""
        index = self.today.year * 12 + self.today.month - 1 - self.historique
        return datetime.date(index // 12, index % 12 + 1, 1)

    def aware(self, day: datetime.date, hour: int = 12, minute: int = 0, second: int = 0) -> datetime.datetime:
        return timezone.make_aware(datetime.datetime(day.year, day.month, day.day, hour, minute, second))

    # --- Traces ----------------------------------------------------------------------------------

    def track(self, model: type[models.Model] | str, ids: Iterable[Any]) -> int:
        from apps.core.models import SeedRecord

        label = model if isinstance(model, str) else model._meta.label_lower
        rows = [
            SeedRecord(batch=self.batch, seeder=self.current_seeder, model=label, object_id=str(i)) for i in ids
        ]
        SeedRecord.objects.bulk_create(rows, batch_size=5000, ignore_conflicts=True)
        return len(rows)

    def tracked_ids(self, model: type[models.Model] | str, seeder: str | None = None) -> list[str]:
        from apps.core.models import SeedRecord

        label = model if isinstance(model, str) else model._meta.label_lower
        qs = SeedRecord.objects.filter(batch=self.batch, model=label)
        if seeder:
            qs = qs.filter(seeder=seeder)
        return list(qs.values_list("object_id", flat=True))

    def tracked(self, model: type[models.Model], seeder: str | None = None) -> models.QuerySet[Any]:
        return model._default_manager.filter(pk__in=self.tracked_ids(model, seeder))

    def untrack(self, seeder: str) -> None:
        from apps.core.models import SeedRecord

        SeedRecord.objects.filter(batch=self.batch, seeder=seeder).delete()

    def done(self, seeder: str) -> bool:
        from apps.core.models import SeedRecord

        return SeedRecord.objects.filter(batch=self.batch, seeder=seeder, model="_done").exists()

    def mark_done(self, seeder: str) -> None:
        from apps.core.models import SeedRecord

        SeedRecord.objects.get_or_create(batch=self.batch, seeder=seeder, model="_done", object_id=seeder)

    # --- Journal ---------------------------------------------------------------------------------

    def log(self, message: str) -> None:
        if self.stdout is not None:
            self.stdout.write(f"  · {message}")

    def note(self, message: str) -> None:
        """Remarque reprise dans le rapport final (repli, étape sautée…)."""
        self.notes.append(message)
        self.log(message)

    # --- Accès communs -----------------------------------------------------------------------------

    def parishes(self) -> list[Any]:
        """Paroisses peuplées : la pilote, la seconde paroisse de démonstration, puis celles du lot."""
        from apps.core.seeding import world
        from apps.hierarchy.models import Node

        codes = world.parish_codes(self)
        nodes = {n.code: n for n in Node.objects.filter(code__in=codes).select_related("type")}
        return [nodes[c] for c in codes if c in nodes]

    def fideles_qs(self) -> models.QuerySet[Any]:
        """Fidèles du lot (sous-requête sur les traces : pas de liste de 50 000 identifiants)."""
        from django.db.models.functions import Cast

        from apps.core.models import SeedRecord
        from apps.users.models import BaseUser

        ids = (
            SeedRecord.objects.filter(batch=self.batch, seeder="personnes", model=BaseUser._meta.label_lower)
            .annotate(uid=Cast("object_id", models.UUIDField()))
            .values("uid")
        )
        return BaseUser.objects.filter(pk__in=ids, etat_de_vie="laic")

    def members(self, *, primary_only: bool = False) -> dict[Any, list[Any]]:
        """Fidèles du lot par paroisse (appartenances actives), en une requête, gardé en mémoire."""
        key = "primary" if primary_only else "all"
        cache = self.__dict__.setdefault("_members", {})
        if key not in cache:
            from apps.hierarchy.models import ParishMembership

            qs = ParishMembership.objects.filter(
                node__in=self.parishes(), removed_by_parish_at__isnull=True, user__in=self.fideles_qs()
            )
            if primary_only:
                qs = qs.filter(is_primary=True)
            grouped: dict[Any, list[Any]] = {}
            for node_id, user_id in qs.order_by("user_id").values_list("node_id", "user_id"):
                grouped.setdefault(node_id, []).append(user_id)
            cache[key] = grouped
        return cache[key]

    def persona(self, key: str) -> Any:
        from apps.users.models import BaseUser

        return BaseUser.objects.filter(email=f"{key}@{DOMAIN}").first()
