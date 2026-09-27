"""URL signées du CDN, style Cloudflare : ``?verify=<expiration>-<signature>`` (plan §5.3).

La signature couvre le **préfixe versionné** de la piste, pas un fichier :

    prefixe   = "/audio-hls/<track_id>/<version>/"
    message   = prefixe + str(expiration)            # expiration : secondes Unix
    signature = base64url(HMAC-SHA256(AUDIO_CDN_SIGNING_SECRET, message)), sans « = »

Le même jeton vaut donc pour ``master.m3u8``, les manifestes de débit et tous les segments de
cette version : le Worker du CDN recopie ``verify`` sur chaque URI relative quand il sert un
manifeste (voir docs/AUDIO-ARCHITECTURE.md). ``verify_path`` est la référence Python de la
vérification faite par le Worker (mêmes règles, testées ici).
"""

import base64
import hashlib
import hmac
import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX_SEGMENTS = 3  # audio-hls / <track_id> / <version>


def _secret() -> bytes:
    secret = settings.AUDIO_CDN_SIGNING_SECRET
    if not secret:
        raise ImproperlyConfigured("AUDIO_CDN_SIGNING_SECRET est requis quand AUDIO_CDN_BASE_URL est défini.")
    return secret.encode()


def prefix_for_path(path: str) -> str:
    """``/audio-hls/<id>/<v>/bas/seg_00001.ts`` → ``/audio-hls/<id>/<v>/``."""
    parts = [p for p in path.split("/") if p]
    if len(parts) < PREFIX_SEGMENTS:
        raise ValueError("Chemin hors d'un dossier versionné.")
    return "/" + "/".join(parts[:PREFIX_SEGMENTS]) + "/"


def sign_prefix(prefix: str, expires: int) -> str:
    mac = hmac.new(_secret(), f"{prefix}{expires}".encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return f"{expires}-{signature}"


def signed_url(*, key: str, now: float | None = None, ttl: int | None = None) -> tuple[str, int]:
    """URL CDN signée de ``key`` (clé de stockage, sans « / » initial) et son expiration."""
    expires = int((now if now is not None else time.time()) + (ttl or settings.AUDIO_SIGNED_URL_TTL_SECONDS))
    path = "/" + key.lstrip("/")
    token = sign_prefix(prefix_for_path(path), expires)
    return f"{settings.AUDIO_CDN_BASE_URL.rstrip('/')}{path}?verify={token}", expires


def verify_path(path: str, verify: str, *, now: float | None = None) -> bool:
    """Vrai si ``verify`` signe le préfixe de ``path`` et n'a pas expiré."""
    try:
        expires_raw, signature = verify.split("-", 1)
        expires = int(expires_raw)
        prefix = prefix_for_path(path)
    except (ValueError, AttributeError):
        return False
    if expires < (now if now is not None else time.time()):
        return False
    expected = sign_prefix(prefix, expires).split("-", 1)[1]
    return hmac.compare_digest(expected, signature)
