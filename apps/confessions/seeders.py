"""Semeur des confessions (``seed_realiste``, lot S3) : règles, créneaux sur six semaines, réservations
(honorées, absences, annulations). Aucun champ de contenu (RG-08)."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction

from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.hierarchy.seeders import staff_of


@register
class ConfessionsSeeder(Seeder):
    name = "confessions"
    module = "vie"
    phase = Phase.CONTENUS
    depends = ("appartenances",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule
        from apps.hierarchy.models import OfficeAssignment

        rng = ctx.rng(self.name)
        rules, slots, bookings = [], [], []
        adults = list(ctx.fideles_qs().filter(profile__date_of_birth__lte=ctx.today.replace(year=ctx.today.year - 18))
                      .order_by("pk").values_list("pk", flat=True))  # fmt: skip
        for parish in ctx.parishes():
            place = parish.places.filter(is_main=True).first()
            if place is None:
                continue
            priests = [a.person for a in OfficeAssignment.objects.filter(
                node=parish, office_type__code="vicaire_paroissial", status="active").select_related("person").order_by("person_id")]  # fmt: skip
            if ctx.persona("vicaire") in priests:
                priests = [staff_of(parish, "cure")]  # le vicaire persona a déjà sa règle (seed_demo)
            for k, priest in enumerate(priests):
                # JB-WEB-018 : le samedi, les créneaux tombent dans la permanence de confession
                # affichée (16 h-18 h) au lieu de 10 h ; les autres jours restent des créneaux
                # supplémentaires en soirée.
                weekday, hour = [(5, 16), (2, 18), (4, 17)][k % 3]
                rule = ConfessionSlotRule(priest=priest, place=place, weekday=weekday, start_time=datetime.time(hour, 0),
                                          end_time=datetime.time(hour + 1, 0), slot_minutes=15,
                                          valid_from=ctx.today - datetime.timedelta(days=60))  # fmt: skip
                rules.append(rule)
                day = ctx.today - datetime.timedelta(days=14)
                while day <= ctx.today + datetime.timedelta(days=28):
                    if day.weekday() == weekday:
                        for q in range(4):
                            start = ctx.aware(day, hour, 15 * q)
                            slot = ConfessionSlot(rule=rule, priest=priest, place=place, starts_at=start,
                                                  ends_at=start + datetime.timedelta(minutes=15))  # fmt: skip
                            slots.append(slot)
                            past = start < ctx.now
                            if adults and rng.random() < (0.55 if past else 0.3):
                                person = rng.choice(adults)
                                if past:
                                    status = rng.choices(["honoree", "absent", "annulee_fidele"], [80, 10, 10])[0]
                                else:
                                    status = rng.choices(["reservee", "annulee_fidele", "annulee_pretre"], [85, 10, 5])[0]
                                cancelled = status.startswith("annulee")
                                bookings.append(ConfessionBooking(
                                    slot=slot, person_id=person, status=status,
                                    cancelled_at=start - datetime.timedelta(hours=rng.randint(3, 48)) if cancelled else None,
                                    cancel_message="Empêchement, je réserverai un autre créneau." if status == "annulee_fidele" else
                                    ("Absence imprévue du prêtre. Merci de choisir un autre créneau." if status == "annulee_pretre" else ""),
                                ))  # fmt: skip
                                slot.status = {"reservee": "reserve", "annulee_pretre": "bloque"}.get(status, "reserve" if not cancelled else "libre")
                    day += datetime.timedelta(days=1)
        with transaction.atomic():
            ConfessionSlotRule.objects.bulk_create(rules)
            ConfessionSlot.objects.bulk_create(slots)
            ConfessionBooking.objects.bulk_create(bookings)
            ctx.track(ConfessionSlotRule, [r.pk for r in rules])
            ctx.track(ConfessionSlot, [s.pk for s in slots])
        return {"regles": len(rules), "creneaux": len(slots), "reservations": len(bookings)}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.confessions.models import ConfessionSlot, ConfessionSlotRule

        n, _ = ctx.tracked(ConfessionSlot).delete()
        ctx.tracked(ConfessionSlotRule).delete()
        return {"objets": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.confessions.models import ConfessionBooking, ConfessionSlot

        slots = ctx.tracked(ConfessionSlot)
        b = ConfessionBooking.objects.filter(slot__in=slots)
        return [Check("Créneaux de confession réservables", slots.filter(status="libre").exists(),
                      f"{slots.count()} créneaux, {b.count()} réservations dont {b.filter(status__startswith='annulee').count()} annulées")]  # fmt: skip
