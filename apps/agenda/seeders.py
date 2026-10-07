"""Semeur de l'agenda (``seed_realiste``, lot S3) : événements passés et à venir, avec inscriptions."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction

from apps.core.seeding import textes
from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.hierarchy.seeders import staff_of


@register
class AgendaSeeder(Seeder):
    name = "agenda"
    module = "vie"
    phase = Phase.CONTENUS
    depends = ("appartenances",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.agenda.models import Event, EventRegistration

        rng = ctx.rng(self.name)
        catalogue = textes()["evenements"]
        events, registrations = [], []
        for parish in ctx.parishes():
            organizer = staff_of(parish, "cure")
            place = parish.places.filter(is_main=True).first()
            members = ctx.members().get(parish.pk, [])
            for i in range(ctx.scale.evenements_par_paroisse):
                title, kind, capacity = catalogue[(i + rng.randint(0, 3)) % len(catalogue)]
                offset = rng.randint(-60, 45)
                # JB-WEB-006 : une veillée est un événement du soir (horaires cohérents).
                hours = [19, 20, 21] if "eillée" in title or "igile" in title else [9, 10, 16, 18, 19]
                start = ctx.aware(ctx.today + datetime.timedelta(days=offset), rng.choice(hours))
                e = Event(
                    title=title, description=f"{title} à {parish.name.removeprefix('Paroisse ')}. Tous sont les bienvenus.",
                    event_type=kind, start_at=start, end_at=start + datetime.timedelta(hours=rng.choice([2, 3])),
                    location=place.name if place else parish.name, organizer=organizer, scope_node=parish,
                    scope_place=place, max_participants=capacity if rng.random() < 0.7 else None,
                    registration_closes_at=start - datetime.timedelta(hours=12),
                    reminder_sent_at=start - datetime.timedelta(days=1) if offset < 0 else None,
                )  # fmt: skip
                if i == 1 and offset > 0:
                    e.cancelled_at, e.cancelled_by = ctx.now - datetime.timedelta(days=1), organizer
                events.append(e)
                if members:
                    for u in rng.sample(members, k=min(len(members), rng.randint(3, 30))):
                        registrations.append(
                            EventRegistration(event=e, user_id=u, seats=rng.choices([1, 2, 3, 4], [70, 18, 8, 4])[0],
                                              note="Nous viendrons en famille." if rng.random() < 0.05 else "")
                        )  # fmt: skip
        with transaction.atomic():
            Event.objects.bulk_create(events)
            EventRegistration.objects.bulk_create(registrations, ignore_conflicts=True)
            ctx.track(Event, [e.pk for e in events])
        return {"evenements": len(events), "inscriptions": len(registrations)}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.agenda.models import Event

        n, _ = ctx.tracked(Event).delete()
        return {"objets": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.agenda.models import Event, EventRegistration

        events = ctx.tracked(Event)
        regs = EventRegistration.objects.filter(event__in=events).count()
        return [Check("Événements avec inscriptions", regs > 0, f"{events.count()} événements, {regs} inscriptions")]
