"""Accès au stockage objet de la sonothèque : local (``FileSystemStorage``) ou S3/MinIO/R2 selon
``FILE_UPLOAD_STORAGE``, comme ``apps.files``.

En S3, on passe par le client boto3 d'``apps.integrations.aws`` pour poser ``Content-Type`` et
``Cache-Control`` fichier par fichier (segments immuables un an, manifestes 60 s, §5.6).
"""

import mimetypes
import os
import shutil
from typing import Any

from django.conf import settings
from django.core.files import File as DjangoFile
from django.core.files.storage import default_storage

from apps.files.enums import FileUploadStorage
from apps.integrations.aws.client import s3_get_client, s3_get_credentials

IMMUTABLE = "public, max-age=31536000, immutable"
MANIFEST = "public, max-age=60"

CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".aac": "audio/aac",
    ".m4s": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".json": "application/json",
}


def is_s3() -> bool:
    return settings.FILE_UPLOAD_STORAGE == FileUploadStorage.S3


def content_type_for(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return CONTENT_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def cache_control_for(name: str) -> str:
    return MANIFEST if name.endswith(".m3u8") else IMMUTABLE


def put_file(*, key: str, local_path: str) -> int:
    """Dépose ``local_path`` sous ``key`` (écrase : les chemins sont versionnés). Renvoie la taille."""
    size = os.path.getsize(local_path)
    if is_s3():
        credentials = s3_get_credentials()
        s3_get_client().upload_file(
            local_path,
            credentials.bucket_name,
            key,
            ExtraArgs={"ContentType": content_type_for(key), "CacheControl": cache_control_for(key)},
        )
        return size
    if default_storage.exists(key):
        default_storage.delete(key)
    with open(local_path, "rb") as fh:
        saved = default_storage.save(key, DjangoFile(fh))
    if saved != key:  # pragma: no cover - garde-fou : FileSystemStorage renommerait en cas de course
        raise RuntimeError(f"Chemin de stockage inattendu : {saved} au lieu de {key}")
    return size


def download(*, key: str, local_path: str) -> None:
    if is_s3():
        credentials = s3_get_credentials()
        s3_get_client().download_file(credentials.bucket_name, key, local_path)
        return
    with default_storage.open(key, "rb") as src, open(local_path, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)


def head(*, key: str) -> dict[str, Any] | None:
    """Taille et type d'un objet, ou ``None`` s'il n'existe pas."""
    if is_s3():
        from botocore.exceptions import ClientError

        credentials = s3_get_credentials()
        try:
            response = s3_get_client().head_object(Bucket=credentials.bucket_name, Key=key)
        except ClientError:
            return None
        return {"size": int(response.get("ContentLength", 0)), "content_type": response.get("ContentType", "")}
    if not default_storage.exists(key):
        return None
    return {"size": default_storage.size(key), "content_type": ""}


def delete_prefix(*, prefix: str) -> None:
    """Supprime un dossier versionné (échec partiel d'un encodage)."""
    if is_s3():
        credentials = s3_get_credentials()
        client = s3_get_client()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=credentials.bucket_name, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=credentials.bucket_name, Delete={"Objects": keys})
        return
    root = default_storage.path(prefix)
    if os.path.isdir(root):
        shutil.rmtree(root)


def presigned_get(*, key: str, expires_in: int) -> str:
    """URL MinIO/S3 présignée (développement sans CDN)."""
    credentials = s3_get_credentials()
    url = s3_get_client().generate_presigned_url(
        "get_object", Params={"Bucket": credentials.bucket_name, "Key": key}, ExpiresIn=expires_in
    )
    public = getattr(settings, "MINIO_PUBLIC_URL", "")
    endpoint = getattr(settings, "AWS_S3_ENDPOINT_URL", None)
    if public and endpoint and url.startswith(endpoint):
        url = public.rstrip("/") + url[len(endpoint.rstrip("/")) :]
    return url


def presigned_post(*, key: str, content_type: str, max_size: int, expires_in: int) -> dict[str, Any]:
    """POST présigné vers le bucket privé, limité en type et en taille (500 Mo pour l'audio)."""
    credentials = s3_get_credentials()
    return s3_get_client().generate_presigned_post(
        credentials.bucket_name,
        key,
        Fields={"acl": "private", "Content-Type": content_type},
        Conditions=[
            {"acl": "private"},
            {"Content-Type": content_type},
            ["content-length-range", 1, max_size],
        ],
        ExpiresIn=expires_in,
    )


def local_url(*, key: str) -> str:
    return f"{settings.APP_DOMAIN}{settings.MEDIA_URL}{key}"
