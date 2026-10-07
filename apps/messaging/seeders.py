"""Semeur de la messagerie et des notifications (``seed_realiste``, lot S3) : conversations prêtre–fidèle
chiffrées (fils courts), un blocage, disponibilités des prêtres ; notifications et préférences variées.
Push : aucun appareil enregistré (plan §2). Les mineurs n'ont aucune conversation (RG-13 ; le refus
s'essaie avec la persona « mineur »)."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction

from apps.core.seeding import textes
from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register


@register
class MessagerieSeeder(Seeder):
    name = "messagerie"
    module = "vie"
    phase = Phase.CONTENUS
    depends = ("appartenances", "annonces", "actes", "agenda")

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy.models import OfficeAssignment, ParishMembership
        from apps.messaging.models import (
            Conversation,
            Message,
            MessageBlock,
            MessagingAvailability,
            MessagingCguAcceptance,
            Notification,
            NotificationPreference,
        )

        rng = ctx.rng(self.name)
        threads = textes()["messages"]
        adult_cut = ctx.today.replace(year=ctx.today.year - 18)
        priests_of: dict[Any, list[Any]] = {}
        for a in OfficeAssignment.objects.filter(node__in=ctx.parishes(), status="active",
                                                 office_type__code__in=["cure", "vicaire_paroissial"]).order_by("person_id"):  # fmt: skip
            priests_of.setdefault(a.node_id, []).append(a.person_id)
        members = list(
            ParishMembership.objects.filter(node__in=ctx.parishes(), is_primary=True, removed_by_parish_at__isnull=True,
                                            user__in=ctx.fideles_qs(), user__profile__date_of_birth__lte=adult_cut)
            .order_by("user_id").values_list("node_id", "user_id")
        )  # fmt: skip
        conversations, messages, pairs = [], [], set()
        for _ in range(ctx.scale.conversations if members else 0):
            node_id, fidele = rng.choice(members)
            if not priests_of.get(node_id):
                continue
            priest = rng.choice(priests_of[node_id])
            a, b = sorted([priest, fidele], key=str)
            if (a, b) in pairs:
                continue
            pairs.add((a, b))
            start = ctx.now - datetime.timedelta(days=rng.randint(1, 80), hours=rng.randint(0, 10))
            conv = Conversation(participant_a_id=a, participant_b_id=b, cgu_accepted_by_a=start, cgu_accepted_by_b=start,
                                created_at=start)  # fmt: skip
            at = start
            for i, (who, text) in enumerate(rng.choice(threads)):
                at = at + datetime.timedelta(minutes=rng.randint(5, 600))
                messages.append(Message(conversation=conv, sender_id=fidele if who == "fidele" else priest, content=text,
                                        created_at=at, read_at=at + datetime.timedelta(minutes=rng.randint(1, 120))
                                        if (i < 2 or rng.random() < 0.6) else None))  # fmt: skip
            conv.last_message_at = at
            conversations.append(conv)
        with transaction.atomic():
            Conversation.objects.bulk_create(conversations)
            Message.objects.bulk_create(messages, batch_size=2000)
            ctx.track(Conversation, [c.pk for c in conversations])
            participants = {c.participant_a_id for c in conversations} | {c.participant_b_id for c in conversations}
            existing = set(
                MessagingCguAcceptance.objects.filter(user_id__in=participants).values_list("user_id", flat=True)
            )
            cgu = [MessagingCguAcceptance(user_id=u, accepted_at=ctx.now - datetime.timedelta(days=90))
                   for u in participants - existing]  # fmt: skip
            MessagingCguAcceptance.objects.bulk_create(cgu)
            ctx.track(MessagingCguAcceptance, [c.pk for c in cgu])
            all_priests = {p for ps in priests_of.values() for p in ps}
            have = set(MessagingAvailability.objects.filter(user_id__in=all_priests).values_list("user_id", flat=True))
            avail = []
            for p in sorted(all_priests - have, key=str):
                absent = rng.random() < 0.15
                avail.append(MessagingAvailability(
                    user_id=p, accepts_new_conversations=rng.random() > 0.1,
                    absent_until=ctx.today + datetime.timedelta(days=rng.randint(3, 15)) if absent else None,
                    reply_windows=[
                        {"weekday": d, "start": "17:00", "end": "19:00"} for d in (1, 2, 3, 4, 5)
                    ],
                    note="En retraite annuelle, je réponds à mon retour." if absent else "",
                ))  # fmt: skip
            MessagingAvailability.objects.bulk_create(avail)
            ctx.track(MessagingAvailability, [x.pk for x in avail])
            blocks = []
            if conversations:
                c = conversations[-1]
                blocks.append(MessageBlock(blocker_id=c.participant_a_id, blocked_id=c.participant_b_id))
                MessageBlock.objects.bulk_create(blocks, ignore_conflicts=True)
                ctx.track(MessageBlock, [x.pk for x in blocks])

            notifications = self._notifications(ctx, rng)
            Notification.objects.bulk_create(notifications, batch_size=5000)
            fideles = list(ctx.fideles_qs().order_by("pk").values_list("pk", flat=True))
            prefs = [
                NotificationPreference(user_id=u, in_app=True, email=rng.random() < 0.6, push=rng.random() < 0.7,
                                       topic_annonces=rng.random() < 0.85, topic_evenements=rng.random() < 0.8)
                for u in fideles if rng.random() < 0.3
            ]  # fmt: skip
            NotificationPreference.objects.bulk_create(prefs, ignore_conflicts=True)
        return {"conversations": len(conversations), "messages": len(messages), "blocages": len(blocks),
                "notifications": len(notifications), "preferences": len(prefs)}  # fmt: skip

    def _notifications(self, ctx: SeedContext, rng: Any) -> list[Any]:
        from apps.agenda.models import EventRegistration
        from apps.documents.models import DocumentRequest
        from apps.messaging.models import Notification
        from apps.news.models import Article

        out: list[Any] = []
        for a in (
            ctx.tracked(Article).filter(status="published", scope_node__isnull=False).order_by("-published_at")[:6]
        ):
            readers = list(ctx.fideles_qs().filter(paroisse_suivie=a.scope_node).values_list("pk", flat=True)[:400])
            for u in readers:
                out.append(Notification(user_id=u, event_type="news.published", is_read=rng.random() < 0.6,
                                        payload={"article_id": str(a.pk), "title": a.title, "node_name": a.scope_node.name},
                                        created_at=a.published_at))  # fmt: skip
        for r in ctx.tracked(DocumentRequest).exclude(status="submitted"):
            out.append(Notification(user_id=r.requester_id, event_type="documents.status", is_read=rng.random() < 0.5,
                                    payload={"request_id": str(r.pk), "reference": r.reference, "status": r.status}))  # fmt: skip
        for reg in EventRegistration.objects.filter(event__start_at__lt=ctx.now).select_related("event")[:300]:
            if reg.user_id and rng.random() < 0.5:
                e = reg.event
                out.append(Notification(user_id=reg.user_id, event_type="agenda.reminder", is_read=True,
                                        payload={"event_id": e.pk, "title": e.title, "start_at": e.start_at.isoformat()},
                                        created_at=e.start_at - datetime.timedelta(days=1)))  # fmt: skip
        return out

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.messaging.models import (
            Conversation,
            MessageBlock,
            MessagingAvailability,
            MessagingCguAcceptance,
            Notification,
        )

        n, _ = ctx.tracked(Conversation).delete()
        ctx.tracked(MessageBlock).delete()
        ctx.tracked(MessagingAvailability).delete()
        ctx.tracked(MessagingCguAcceptance).delete()
        # Notifications des personas liées aux objets du lot (les fidèles du lot les emportent avec eux).
        from apps.documents.models import DocumentRequest

        refs = [str(pk) for pk in ctx.tracked_ids(DocumentRequest)]
        Notification.objects.filter(event_type="documents.status", payload__request_id__in=refs).delete()
        return {"conversations": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.messaging.models import Conversation, Message

        convs = ctx.tracked(Conversation)
        minors = convs.filter(
            participant_b__profile__date_of_birth__gt=ctx.today.replace(year=ctx.today.year - 18)
        ).count()
        minors += convs.filter(
            participant_a__profile__date_of_birth__gt=ctx.today.replace(year=ctx.today.year - 18)
        ).count()
        return [Check("Messagerie réservée aux majeurs (RG-13)", minors == 0,
                      f"{convs.count()} conversations, {Message.objects.filter(conversation__in=convs).count()} messages")]  # fmt: skip
