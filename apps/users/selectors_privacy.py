"""Export des données personnelles (SRS EF-CONF-02 ; EF-PRE-08).

Tout ce que l'application détient sur la personne, sous une forme lisible. Les messages
exportés sont ceux qu'elle a écrits (ceux de ses correspondants sont leurs données) ; les
notes internes des paroisses n'en font pas partie (elles relèvent du traitement paroissial).
"""

from typing import Any

from django.db.models import Q
from django.utils import timezone


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def personal_data_export(*, user: Any) -> dict[str, Any]:
    from django.db.models import Prefetch

    from apps.agenda.models import EventRegistration
    from apps.confessions.models import ConfessionBooking
    from apps.documents.models import DocumentRequest
    from apps.messaging.models import Conversation, Message, NotificationPreference

    profile = getattr(user, "profile", None)
    own_messages = Message.objects.filter(sender=user, deleted_at__isnull=True).order_by("created_at")
    conversations = Conversation.objects.filter(Q(participant_a=user) | Q(participant_b=user)).prefetch_related(
        Prefetch("messages", queryset=own_messages, to_attr="own_messages")
    )
    preference = NotificationPreference.objects.filter(user=user).first()
    return {
        "generated_at": timezone.now().isoformat(),
        "account": {
            "id": str(user.pk),
            "email": user.email,
            "phone_number": str(user.phone_number) if user.phone_number else None,
            "created_at": _iso(user.created_at),
            "etat_de_vie": user.etat_de_vie,
            "degre_ordre": user.degre_ordre,
            "paroisse_suivie": user.paroisse_suivie.name if user.paroisse_suivie else None,
            "consent_version": user.consent_version,
            "consent_at": _iso(user.consent_at),
        },
        "profile": {
            "first_name": getattr(profile, "first_name", ""),
            "last_name": getattr(profile, "last_name", ""),
            "date_of_birth": _iso(getattr(profile, "date_of_birth", None)),
        },
        "notification_preferences": {
            "in_app": preference.in_app,
            "email": preference.email,
            "topic_annonces": preference.topic_annonces,
            "topic_evenements": preference.topic_evenements,
            "quiet_start": _iso(preference.quiet_start),
            "quiet_end": _iso(preference.quiet_end),
        }
        if preference
        else None,
        "document_requests": [
            {
                "reference": r.reference,
                "document_type": r.document_type,
                "status": r.status,
                "target": r.target_node.name if r.target_node else None,
                "created_at": _iso(r.created_at),
                "requester_last_name": r.requester_last_name,
                "requester_first_names": r.requester_first_names,
                "date_of_birth": _iso(r.date_of_birth),
                "contact_phone": r.contact_phone,
                "contact_email": r.contact_email,
            }
            for r in DocumentRequest.objects.filter(requester=user).select_related("target_node").order_by("created_at")
        ],
        "confession_bookings": [
            {"starts_at": _iso(b.slot.starts_at), "place": b.slot.place.name, "status": b.status}
            for b in ConfessionBooking.objects.filter(person=user).select_related("slot", "slot__place")
        ],
        "event_registrations": [
            {"event": r.event.title, "start_at": _iso(r.event.start_at), "registered_at": _iso(r.registered_at)}
            for r in EventRegistration.objects.filter(user=user).select_related("event")
        ],
        "conversations": [
            {
                "id": str(c.pk),
                "created_at": _iso(c.created_at),
                "my_messages": [{"sent_at": _iso(m.created_at), "content": m.content} for m in c.own_messages],
            }
            for c in conversations.order_by("created_at")
        ],
    }
