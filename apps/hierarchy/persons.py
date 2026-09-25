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
