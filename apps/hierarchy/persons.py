"""État ecclésial d'une personne (SRS §5.2). Remplace l'ancien ``pastoral_role`` pour les
quelques contrôles qui portent sur l'état de vie et non sur un office."""

from typing import Any

from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification

PRIEST_DEGREES = frozenset({DegreOrdre.PRETRE, DegreOrdre.EVEQUE})


def _verified(user: Any) -> bool:
    return getattr(user, "statut_verification", None) == StatutVerification.VERIFIE


def is_clerc_or_consecrated(user: Any) -> bool:
    """Clerc (diacre, prêtre, évêque) ou consacré, dont l'état est vérifié."""
    return _verified(user) and getattr(user, "etat_de_vie", EtatDeVie.LAIC) != EtatDeVie.LAIC


def is_priest_or_bishop(user: Any) -> bool:
    return _verified(user) and getattr(user, "degre_ordre", None) in PRIEST_DEGREES


def email_mask(email: str) -> str:
    """« augustin.ndiaye@gmail.com » → « a•••e@gmail.com » : assez pour distinguer deux
    homonymes, pas assez pour écrire à la personne (recherche de personne à nommer)."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "•••"
    shown = local[0] + "•••" + local[-1] if len(local) > 2 else local[:1] + "•••"
    return f"{shown}@{domain}"


def full_name(user: Any) -> str:
    """Prénom et nom du profil ; chaîne vide s'ils ne sont pas renseignés."""
    profile = getattr(user, "profile", None)
    return f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
