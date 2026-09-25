"""Conversion des droits de l'ancien modèle vers les nominations (plan L2.9, SRS §5.4).

Deux temps : ``legacy_rights_plan()`` produit la table de correspondance « qui devient
quoi » SANS rien écrire (à relire et valider par un humain) ; ``legacy_rights_apply()``
applique ce plan. Les nominations issues de la migration contournent la condition
d'ordre (les statuts cléricaux hérités sont « déclarés », RG-07) : elles sont
marquées dans ``note`` et doivent être revues par la chancellerie.
"""

import csv
import io
from dataclasses import dataclass
from functools import partial
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.enums import AssignmentStatus, DegreOrdre, EtatDeVie, StatutVerification
from apps.hierarchy.models import Node, OfficeAssignment, OfficeType

PRIEST_ROLES = {"pretre", "eveque", "archeveque"}
PASTORAL_TO_STATE = {
    "fidele": (EtatDeVie.LAIC, DegreOrdre.AUCUN),
    "religieux": (EtatDeVie.CONSACRE, DegreOrdre.AUCUN),
    "diacre": (EtatDeVie.CLERC, DegreOrdre.DIACRE_PERMANENT),
    "pretre": (EtatDeVie.CLERC, DegreOrdre.PRETRE),
    "eveque": (EtatDeVie.CLERC, DegreOrdre.EVEQUE),
    "archeveque": (EtatDeVie.CLERC, DegreOrdre.EVEQUE),
}
CSV_COLUMNS = ["source", "email", "ancien", "office", "node_code", "action", "remarque"]


@dataclass
class PlanRow:
    source: str
    email: str
    ancien: str
    office: str = ""
    node_code: str = ""
    action: str = "creer"  # creer | profil | manuel | ignorer
    remarque: str = ""
    person_id: Any = None
    start_date: Any = None


def _legacy_node(model: str, legacy_id: Any) -> Node | None:
    if legacy_id is None:
        return None
    return Node.objects.filter(legacy_model=model, legacy_id=legacy_id).first()


def _assignment_rows() -> list[PlanRow]:
    from apps.users.models import RoleAssignment

    rows: list[PlanRow] = []
    seen_cure: set[Any] = set()
    qs = RoleAssignment.objects.filter(is_active=True).select_related("user", "church").order_by(
        "-is_principal", "created_at"
    )
    for ra in qs:
        user = ra.user
        base = PlanRow(
            source=f"RoleAssignment#{ra.pk}",
            email=user.email,
            ancien=f"{ra.role}@{ra.scope}",
            person_id=user.pk,
            start_date=ra.start_date,
        )
        priest = user.pastoral_role in PRIEST_ROLES
        if ra.role == "super_admin":
            rows.append(_with(base, action="manuel", remarque="Rôle Keycloak platform_admin (lot L3), pas de nomination."))
        elif ra.role == "province_admin":
            rows.append(_with(base, action="manuel", remarque="Pas d'équivalent (province masquée) : nommer par diocèse."))
        elif ra.role == "diocese_admin":
            node = _legacy_node("org.Diocese", ra.diocese_id)
            rows.append(_target(base, "delegue_numerique_diocesain", node))
        elif ra.role == "parish_admin":
            node = _legacy_node("org.Parish", ra.parish_id)
            if priest and node is not None and node.pk not in seen_cure:
                seen_cure.add(node.pk)
                rows.append(_target(base, "cure", node))
            elif priest:
                rows.append(_target(base, "vicaire_paroissial", node, "Second prêtre administrateur : vicaire."))
            else:
                rows.append(_target(base, "referent_numerique", node))
        elif ra.role == "church_admin":
            node = _legacy_node("org.Parish", ra.church.parish_id if ra.church else None)
            office = "vicaire_paroissial" if priest else "secretaire_paroissial"
            rows.append(_target(base, office, node, "Administrateur d'église : À VALIDER À LA MAIN."))
        else:
            rows.append(_with(base, action="ignorer", remarque="Rôle sans capacité."))
    return rows


def _with(row: PlanRow, **changes: Any) -> PlanRow:
    return PlanRow(**{**row.__dict__, **changes})


def _target(row: PlanRow, office: str, node: Node | None, remark: str = "") -> PlanRow:
    if node is None:
        return _with(row, office=office, action="manuel", remarque="Nœud hérité introuvable (migration org absente ?).")
    return _with(row, office=office, node_code=node.code, remarque=remark)


def _deanery_rows() -> list[PlanRow]:
    from apps.org.models import Deanery

    rows = []
    for deanery in Deanery.objects.exclude(dean__isnull=True).select_related("dean"):
        if deanery.dean is None:  # exclu par la requête ; garde pour le typage
            continue
        node = _legacy_node("org.Deanery", deanery.pk)
        base = PlanRow(source=f"Deanery#{deanery.pk}", email=deanery.dean.email, ancien="dean", person_id=deanery.dean_id)
        rows.append(_target(base, "doyen", node))
    return rows


def _profile_rows() -> list[PlanRow]:
    """État de vie (pastoral_role) et paroisse suivie (appartenance principale)."""
    from apps.users.models import Membership

    User = get_user_model()
    primary = {
        m.user_id: m.church.parish_id
        for m in Membership.objects.filter(is_primary=True).select_related("church")
    }
    rows = []
    for user in User.objects.all().select_related("profile").order_by("email"):
        parish_id = primary.get(user.pk) or getattr(getattr(user, "profile", None), "primary_parish_id", None)
        parish = _legacy_node("org.Parish", parish_id)
        state = PASTORAL_TO_STATE.get(user.pastoral_role or "fidele", (EtatDeVie.LAIC, DegreOrdre.AUCUN))
        changes = []
        if state != (EtatDeVie.LAIC, DegreOrdre.AUCUN):
            changes.append(f"etat_de_vie={state[0]}, degre_ordre={state[1]} (déclaré)")
        if parish is not None:
            changes.append(f"paroisse_suivie={parish.code}")
        if changes:
            rows.append(
                PlanRow(
                    source=f"BaseUser#{user.pk}",
                    email=user.email,
                    ancien=user.pastoral_role or "fidele",
                    node_code=parish.code if parish else "",
                    action="profil",
                    remarque="; ".join(changes),
                    person_id=user.pk,
                )
            )
    return rows


def legacy_rights_plan() -> list[PlanRow]:
    """Plan de conversion, sans aucune écriture."""
    return [*_assignment_rows(), *_deanery_rows(), *_profile_rows()]


def plan_to_csv(rows: list[PlanRow]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: getattr(row, k) for k in CSV_COLUMNS})
    return buffer.getvalue()


@transaction.atomic
def legacy_rights_apply(*, rows: list[PlanRow], actor: Any = None) -> dict[str, int]:
    """Applique un plan validé. Idempotent : une nomination identique déjà ouverte est sautée."""
    User = get_user_model()
    counts = {"nominations": 0, "profils": 0, "sautees": 0}
    today = timezone.localdate()
    offices = {o.code: o for o in OfficeType.objects.all()}
    for row in rows:
        person = User.objects.get(pk=row.person_id)
        if row.action == "profil":
            state = PASTORAL_TO_STATE.get(row.ancien, (EtatDeVie.LAIC, DegreOrdre.AUCUN))
            person.etat_de_vie, person.degre_ordre = state
            if state[0] != EtatDeVie.LAIC and person.statut_verification != StatutVerification.VERIFIE:
                person.statut_verification = StatutVerification.DECLARE
            if row.node_code:
                person.paroisse_suivie = Node.objects.filter(code=row.node_code).first()
            person.save(update_fields=["etat_de_vie", "degre_ordre", "statut_verification", "paroisse_suivie"])
            counts["profils"] += 1
            continue
        if row.action != "creer":
            continue
        node = Node.objects.get(code=row.node_code)
        office = offices[row.office]
        exists = OfficeAssignment.objects.filter(
            person=person, office_type=office, node=node, status__in=[AssignmentStatus.PROPOSEE, AssignmentStatus.ACTIVE]
        ).exists()
        if exists:
            counts["sautees"] += 1
            continue
        assignment = OfficeAssignment.objects.create(
            person=person,
            office_type=office,
            node=node,
            start_date=row.start_date or today,
            status=AssignmentStatus.ACTIVE,
            note=f"Migré depuis {row.source} — à revoir par la chancellerie."[:255],
        )
        audit_log(actor=actor, action="office.migration", target=assignment, node=node, metadata={"source": row.source})
        authz.invalidate_user(person.pk)
        transaction.on_commit(partial(authz.invalidate_user, person.pk))
        counts["nominations"] += 1
    return counts
