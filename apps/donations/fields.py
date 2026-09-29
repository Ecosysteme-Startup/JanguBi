"""Chiffrement au repos des payloads de l'agrégateur (loi 2008-12 : le don révèle la religion
et des finances). Clé propre au module : ``DONATIONS_PAYLOAD_KEY``, sinon dérivée de ``SECRET_KEY``
avec un sel distinct (aucun partage de clé avec la messagerie)."""

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    key = getattr(settings, "DONATIONS_PAYLOAD_KEY", "") or f"donations:{settings.SECRET_KEY}"
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


class EncryptedTextField(models.TextField):
    """Texte chiffré (Fernet) de façon transparente. Un contenu illisible est rendu vide."""

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        if not value:
            return value
        return decrypt_text(value)

    def get_prep_value(self, value: Any) -> Any:
        if value is None or value == "":
            return value
        return encrypt_text(str(value))
