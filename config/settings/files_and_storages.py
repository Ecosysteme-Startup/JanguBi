import os

from apps.files.enums import FileUploadStorage, FileUploadStrategy
from config.env import BASE_DIR, env, env_to_enum

FILE_UPLOAD_STRATEGY = env_to_enum(FileUploadStrategy, env("FILE_UPLOAD_STRATEGY", default="standard"))
FILE_UPLOAD_STORAGE = env_to_enum(FileUploadStorage, env("FILE_UPLOAD_STORAGE", default="local"))

FILE_MAX_SIZE = env.int("FILE_MAX_SIZE", default=10485760)  # 10 MiB

# Liste blanche des types de fichiers acceptés à l'upload.
#
# Pourquoi une liste BLANCHE et pas une liste noire : seule la taille était
# vérifiée, donc n'importe quel utilisateur authentifié pouvait déposer un
# fichier arbitraire. Les fichiers sont ensuite servis depuis MinIO/S3 avec le
# type déclaré ; un `.html` ou un `.svg` (qui peut porter un `<script>`)
# redistribué sous ce type devient un XSS stocké, sur un lien que le fidèle a
# toute raison de croire officiel. Une liste noire se contourne toujours par le
# type qu'on n'a pas pensé à interdire.
#
# Le périmètre correspond aux usages réels : pièces justificatives des demandes
# de documents (scans), photos de profil, et audio pour les contenus spirituels.
# `image/svg+xml` est délibérément ABSENT : c'est un document exécutable
# déguisé en image. Ajouter un type ici, c'est accepter qu'un utilisateur
# quelconque le fasse servir par notre domaine — le faire en connaissance.
FILE_UPLOAD_ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
    "image/heic": (".heic",),  # format par défaut des iPhone
    "audio/mpeg": (".mp3",),
    "audio/mp4": (".m4a",),
    "audio/ogg": (".ogg",),
}

# Réglage unifié des backends de stockage (Django 4.2+ ; remplace les
# STATICFILES_STORAGE / DEFAULT_FILE_STORAGE SUPPRIMÉS en Django 5.1).
#   default     : media — FileSystem en local, S3 (django-storages) en prod.
#   staticfiles : défaut Django ici ; la prod l'override en WhiteNoise manifest
#                 (compression + cache-busting) dans config/django/production.py.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

if FILE_UPLOAD_STORAGE == FileUploadStorage.LOCAL:
    MEDIA_ROOT_NAME = "media"
    MEDIA_ROOT = os.path.join(BASE_DIR, MEDIA_ROOT_NAME)
    MEDIA_URL = f"/{MEDIA_ROOT_NAME}/"

if FILE_UPLOAD_STORAGE == FileUploadStorage.S3:
    # Using django-storages
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html
    STORAGES["default"]["BACKEND"] = "storages.backends.s3boto3.S3Boto3Storage"

    AWS_S3_ACCESS_KEY_ID = env("AWS_S3_ACCESS_KEY_ID")
    AWS_S3_SECRET_ACCESS_KEY = env("AWS_S3_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME")
    AWS_S3_SIGNATURE_VERSION = env("AWS_S3_SIGNATURE_VERSION", default="s3v4")
    AWS_S3_ADDRESSING_STYLE = "path"

    # https://docs.aws.amazon.com/AmazonS3/latest/userguide/acl-overview.html#canned-acl
    AWS_DEFAULT_ACL = env("AWS_DEFAULT_ACL", default="private")

    AWS_PRESIGNED_EXPIRY = env.int("AWS_PRESIGNED_EXPIRY", default=10)  # seconds

    _AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default="")

    if _AWS_S3_CUSTOM_DOMAIN:
        AWS_S3_CUSTOM_DOMAIN = _AWS_S3_CUSTOM_DOMAIN

# URL publique de MinIO — remplace le nom d'hôte Docker interne dans les URLs
# audio générées (apps/rosary/storage.py).
#
# ⚠️ Le défaut DOIT rester vide. `rosary/storage.py` fait
# `MINIO_PUBLIC_URL or AWS_S3_ENDPOINT_URL` : un défaut « http://localhost:9002 »
# est toujours truthy, donc le repli sur l'endpoint réel ne se déclenchait JAMAIS
# et la production servait des URLs pointant vers la machine du visiteur
# (audio du chapelet entièrement mort — audit beta 2026-07-20).
MINIO_PUBLIC_URL = env("MINIO_PUBLIC_URL", default="")

# Audios du chapelet (apps/rosary/storage.py). Historique : un bucket dédié
# `rosary-audio` en lecture anonyme. En recette/production (Infrastructure
# Ecosysteme-Startup), un seul bucket PRIVÉ par environnement (`jangubi-<env>`)
# et un préfixe : ROSARY_AUDIO_BUCKET=jangubi-staging, ROSARY_AUDIO_LOCATION=rosary-audio,
# ROSARY_AUDIO_PUBLIC=false → URL présignées (durée ROSARY_AUDIO_PRESIGNED_EXPIRY).
ROSARY_AUDIO_BUCKET = env("ROSARY_AUDIO_BUCKET", default="rosary-audio")
ROSARY_AUDIO_LOCATION = env("ROSARY_AUDIO_LOCATION", default="").strip("/")
# Faux par défaut : aucune lecture anonyme sauf choix explicite (développement local).
ROSARY_AUDIO_PUBLIC = env.bool("ROSARY_AUDIO_PUBLIC", default=False)
ROSARY_AUDIO_PRESIGNED_EXPIRY = env.int("ROSARY_AUDIO_PRESIGNED_EXPIRY", default=3600)
