"""Semeur des demandes d'actes (``seed_realiste``, lot S3) : tous les statuts, compléments demandés, notes
internes et pièces jointes « SPÉCIMEN — données fictives » générées (PDF et JPEG)."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction

from apps.core.seeding import images, names, textes
from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.hierarchy.seeders import staff_of

STATUSES = [("submitted", 20), ("under_verification", 20), ("info_requested", 10), ("ready_for_pickup", 15),
            ("collected", 20), ("rejected", 5), ("cancelled", 10)]  # fmt: skip
PATHS = {
    "submitted": [],
    "under_verification": ["under_verification"],
    "info_requested": ["under_verification", "info_requested"],
    "ready_for_pickup": ["under_verification", "ready_for_pickup"],
    "collected": ["under_verification", "ready_for_pickup", "collected"],
    "rejected": ["under_verification", "rejected"],
    "cancelled": ["cancelled"],
}
TYPES = [("baptism", "religious_marriage", 40), ("baptism", "godparent", 15), ("confirmation", "religious_marriage", 15),
         ("first_communion", "catechism", 15), ("religious_marriage", "personal", 10), ("godparent", "godparent", 5)]  # fmt: skip
TOWNS = ["Dakar", "Ziguinchor", "Thiès", "Kaolack", "Joal-Fadiouth", "Oussouye", "Saint-Louis", "Rufisque"]


@register
class ActesSeeder(Seeder):
    name = "actes"
    module = "vie"
    phase = Phase.CONTENUS
    depends = ("appartenances",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.documents.models import (
            DocumentRequest,
            DocumentRequestAttachment,
            DocumentRequestStatusLog,
            InternalNote,
        )
        from apps.files.models import File
        from apps.users.models import Profile

        rng = ctx.rng(self.name)
        t = textes()["documents"]
        parishes = ctx.parishes()
        staff = {p.pk: staff_of(p, "secretaire_paroissial") for p in parishes}
        specimens = [
            images.stored_file(name="justificatif-specimen.jpg", content_type="image/jpeg",
                               content=images.specimen_jpeg(label="Pièce d'identité — SPÉCIMEN"))
            for _ in range(2)
        ] + [
            images.stored_file(name="extrait-specimen.pdf", content_type="application/pdf",
                               content=images.specimen_pdf(title="Extrait d'acte de naissance — SPÉCIMEN",
                                                           lines=["Nom : ********", "Né(e) le : ** / ** / ****", "Données fictives."]))
            for _ in range(2)
        ]  # fmt: skip
        ctx.track(File, [f.pk for f in specimens])
        profiles = {p.user_id: p for p in Profile.objects.filter(user__in=ctx.fideles_qs()).order_by("user_id")}
        requesters = [
            (uid, p)
            for uid, p in profiles.items()
            if p.date_of_birth is not None and p.date_of_birth.year < ctx.today.year - 17
        ]
        requests, logs, attachments, notes = [], [], [], []
        for i in range(ctx.scale.demandes_actes if requesters else 0):
            uid, profile = rng.choice(requesters)
            parish = rng.choice(parishes)
            status = rng.choices([s for s, _ in STATUSES], [w for _, w in STATUSES])[0]
            doc_type, reason, _ = rng.choices(TYPES, [w for *_, w in TYPES])[0]
            created = ctx.now - datetime.timedelta(
                days=rng.randint(1 if status == "submitted" else 5, 150), hours=rng.randint(0, 9)
            )
            closed = status in ("collected", "rejected", "cancelled")
            r = DocumentRequest(
                reference=f"DOC-{created:%Y%m%d}-{rng.getrandbits(24):06X}", requester_id=uid, document_type=doc_type,
                reason=reason, status=status, assigned_to=staff[parish.pk] if status != "submitted" else None,
                requester_last_name=profile.last_name, requester_first_names=profile.first_name,
                date_of_birth=profile.date_of_birth or ctx.today.replace(year=1990), place_of_birth=rng.choice(TOWNS), contact_phone=names.phone(i),
                contact_email=f"contact.{i}@demo.jangubi.sn", father_last_name=profile.last_name,
                mother_last_name=rng.choice(names.NOMS), target_node=parish,
                pickup_mode="secretariat" if rng.random() < 0.8 else "transfer_to_followed_parish",
                pickup_hours="Du mardi au samedi, de 9 h à 12 h" if status in ("ready_for_pickup", "collected") else "",
                register_volume=f"B-{rng.randint(1970, 2015)}" if status in ("ready_for_pickup", "collected") else "",
                register_number=str(rng.randint(1, 900)) if status in ("ready_for_pickup", "collected") else "",
                sacrament_approximate_date=str((profile.date_of_birth or ctx.today).year + rng.randint(0, 2)),
                sacrament_location=parish.name.removeprefix("Paroisse "),
                rejection_reason=t["motifs_rejet"][0] if status == "rejected" else "",
                closed_at=created + datetime.timedelta(days=rng.randint(3, 20)) if closed else None,
                consent_given=True, created_at=created,
            )  # fmt: skip
            requests.append(r)
            prev, at = "submitted", created
            logs.append(
                DocumentRequestStatusLog(
                    request=r, from_status="", to_status="submitted", changed_by_id=uid, created_at=created
                )
            )
            for step in PATHS[status]:
                at = at + datetime.timedelta(days=rng.randint(1, 5))
                by_id = uid if step == "cancelled" else getattr(staff[parish.pk], "pk", None)
                comment = rng.choice(t["motifs_complement"]) if step == "info_requested" else ""
                logs.append(DocumentRequestStatusLog(request=r, from_status=prev, to_status=step, changed_by_id=by_id,
                                                     comment=comment, created_at=min(at, ctx.now)))  # fmt: skip
                prev = step
            if rng.random() < 0.35:
                f = rng.choice(specimens)
                attachments.append(DocumentRequestAttachment(request=r, file=f, uploaded_by_id=uid, attachment_type="user_supporting",
                                                              label="Justificatif (spécimen)"))  # fmt: skip
            if status in ("under_verification", "info_requested") and rng.random() < 0.4:
                notes.append(
                    InternalNote(
                        request=r, author=staff[parish.pk], content="Registre consulté, acte à vérifier avec le curé."
                    )
                )
        with transaction.atomic():
            DocumentRequest.objects.bulk_create(requests)
            DocumentRequestStatusLog.objects.bulk_create(logs)
            DocumentRequestAttachment.objects.bulk_create(attachments)
            InternalNote.objects.bulk_create(notes)
            ctx.track(DocumentRequest, [r.pk for r in requests])
        return {"demandes": len(requests), "pieces_jointes": len(attachments), "specimens": len(specimens)}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.documents.models import DocumentRequest
        from apps.files.models import File

        n, _ = ctx.tracked(DocumentRequest).delete()
        for f in ctx.tracked(File, self.name):
            if f.file:
                f.file.delete(save=False)
            f.delete()
        return {"objets": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.documents.models import DocumentRequest

        qs = ctx.tracked(DocumentRequest)
        statuses = set(qs.values_list("status", flat=True))
        return [Check("Demandes d'actes dans plusieurs statuts", len(statuses) >= 4 or qs.count() < 10,
                      f"{qs.count()} demandes, statuts : {', '.join(sorted(statuses))}")]  # fmt: skip
