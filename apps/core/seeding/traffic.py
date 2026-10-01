"""Trafic simulé (``--simuler-trafic 10min``, recette) : des dons confirmés et des événements d'écoute
arrivent en continu par les **vrais services** (paiement factice → notification signée → traitement ;
ingestion des écoutes), pour voir bouger le SSE des tableaux de bord et le temps réel.

Aucune tâche n'est envoyée (reçus, push) : le trafic ne sert qu'à l'affichage. Les dons simulés sont
rattachés aux fonds du lot et disparaissent avec ``--reset``.
"""

from __future__ import annotations

import datetime
import time
import uuid

from django.conf import settings
from django.utils import timezone

from apps.core.seeding.context import DEVICE_ID, SeedContext
from apps.core.seeding.guards import tasks_muted


def simulate(ctx: SeedContext, *, seconds: int) -> None:
    from apps.audio.models import AudioSource, Track
    from apps.audio.services import play_events_ingest
    from apps.donations import services as dons
    from apps.donations.models import Fund
    from apps.donations.providers.base import ProviderStatus
    from apps.donations.providers.fake import FakeProvider
    from apps.users.models import BaseUser

    rng = ctx.rng(f"trafic-{time.time_ns()}")
    from apps.hierarchy.profiles import PILOT_PARISH_CODE

    # Pas la paroisse pilote : son mois de septembre reste exactement celui de la spec.
    funds = list(
        Fund.objects.filter(pk__in=ctx.tracked_ids(Fund), status="ouvert", kind="quete_dominicale").exclude(
            node__code=PILOT_PARISH_CODE
        )
    )
    donors = list(BaseUser.objects.filter(pk__in=ctx.tracked_ids(BaseUser, "personnes"))[:500])
    tracks = list(Track.objects.filter(source__in=ctx.tracked(AudioSource), status="pret", published_at__isnull=False,
                                       effective_visibility="public")[:200])  # fmt: skip
    can_donate = settings.DONATIONS_PROVIDER == "fake" and funds
    if not can_donate:
        ctx.note("Trafic : dons non simulés (agrégateur non factice ou aucun fonds du lot).")
    ctx.log(
        f"trafic simulé pendant {seconds} s : dons {'oui' if can_donate else 'non'}, écoutes {'oui' if tracks else 'non'}"
    )
    deadline = time.monotonic() + seconds
    counts = {"dons": 0, "ecoutes": 0}
    last_report = time.monotonic()
    with tasks_muted():
        while time.monotonic() < deadline:
            if can_donate and rng.random() < 0.35:
                fund = rng.choice(funds)
                donor = rng.choice(donors) if donors else None
                donation, attempt, _ = dons.checkout_create(
                    fund=fund, amount=rng.choice([500, 1_000, 2_000, 2_000, 5_000, 10_000]),
                    fees_covered=rng.random() < 0.25, anonymous=rng.random() < 0.15, donor=donor,
                    source=rng.choice(["app_android", "app_ios", "web", "qr"]),
                )  # fmt: skip
                if attempt.external_ref:
                    headers, body = FakeProvider.simulate(attempt.external_ref, ProviderStatus.COMPLETED,
                                                          method=rng.choice(["wave", "orange_money", "carte"]))  # fmt: skip
                    event, _ = dons.webhook_receive(provider_code="fake", headers=headers, body=body)
                    dons.webhook_process(event_id=event.pk)
                    counts["dons"] += 1
            if tracks and donors:
                user = rng.choice(donors)
                track = rng.choice(tracks)
                now = timezone.now()
                events = [
                    {"client_event_id": uuid.uuid4(), "occurred_at": now, "track_id": track.pk, "kind": "start",
                     "position_seconds": 0, "device_id": DEVICE_ID},
                    {"client_event_id": uuid.uuid4(), "occurred_at": now + datetime.timedelta(seconds=1), "track_id": track.pk,
                     "kind": rng.choice(["progress", "skip"]), "position_seconds": 12, "device_id": DEVICE_ID},
                ]  # fmt: skip
                counts["ecoutes"] += play_events_ingest(user=user, events=events)["enregistres"]
            if time.monotonic() - last_report > 30:
                ctx.log(f"trafic : {counts['dons']} dons confirmés, {counts['ecoutes']} événements d'écoute")
                last_report = time.monotonic()
            time.sleep(rng.uniform(0.5, 2.0))
    ctx.log(f"trafic terminé : {counts['dons']} dons confirmés, {counts['ecoutes']} événements d'écoute")
