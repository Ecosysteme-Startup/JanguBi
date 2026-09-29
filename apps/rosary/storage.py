from urllib.parse import urlparse

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class RosaryAudioStorage(S3Boto3Storage):
    """Stockage S3/MinIO des audios du chapelet.

    Bucket et préfixe configurables (``ROSARY_AUDIO_BUCKET``,
    ``ROSARY_AUDIO_LOCATION``). Par défaut le bucket est PRIVÉ et les URL sont
    présignées ; ``ROSARY_AUDIO_PUBLIC=true`` rétablit, pour le développement
    local seulement, des URL directes sur un bucket en lecture anonyme.

    Les réglages sont lus à l'instanciation (et non à l'import) : la
    déconstruction pour les migrations reste sans argument.
    """

    file_overwrite = False
    default_acl = "private"
    addressing_style = "path"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("bucket_name", getattr(settings, "ROSARY_AUDIO_BUCKET", "rosary-audio"))
        kwargs.setdefault("location", getattr(settings, "ROSARY_AUDIO_LOCATION", ""))
        kwargs.setdefault("access_key", getattr(settings, "AWS_S3_ACCESS_KEY_ID", None))
        kwargs.setdefault("secret_key", getattr(settings, "AWS_S3_SECRET_ACCESS_KEY", None))
        kwargs.setdefault("endpoint_url", getattr(settings, "AWS_S3_ENDPOINT_URL", None))
        kwargs.setdefault("region_name", getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"))
        kwargs.setdefault("signature_version", getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4"))

        public = getattr(settings, "ROSARY_AUDIO_PUBLIC", False)
        kwargs["querystring_auth"] = not public
        if not public:
            # URL présignées : la signature SigV4 porte le nom d'hôte de
            # l'endpoint — surtout pas de custom_domain (il casserait la signature).
            kwargs.setdefault("querystring_expire", getattr(settings, "ROSARY_AUDIO_PRESIGNED_EXPIRY", 3600))
        else:
            custom_domain = (getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "") or "").strip()
            if custom_domain:
                kwargs["custom_domain"] = custom_domain
            else:
                # Adresse publique plutôt que le nom de service Docker interne.
                public_url = getattr(settings, "MINIO_PUBLIC_URL", None) or getattr(
                    settings, "AWS_S3_ENDPOINT_URL", None
                )
                if public_url:
                    parsed = urlparse(public_url)
                    if parsed.netloc:
                        kwargs["custom_domain"] = f"{parsed.netloc}/{kwargs['bucket_name']}"

        super().__init__(*args, **kwargs)

        if public and not getattr(settings, "AWS_S3_USE_SSL", False):
            self.url_protocol = "http:"
