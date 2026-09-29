from django.test import override_settings

from apps.rosary.storage import RosaryAudioStorage

S3 = dict(
    AWS_S3_ACCESS_KEY_ID="cle",
    AWS_S3_SECRET_ACCESS_KEY="secret",
    AWS_S3_ENDPOINT_URL="https://s3.ceac.dev",
    AWS_S3_REGION_NAME="us-east-1",
)


@override_settings(
    **S3, ROSARY_AUDIO_BUCKET="jangubi-staging", ROSARY_AUDIO_LOCATION="rosary-audio", ROSARY_AUDIO_PUBLIC=False
)
def test_bucket_prive_prefixe_et_url_presignee():
    stockage = RosaryAudioStorage()
    assert stockage.bucket_name == "jangubi-staging"
    assert stockage.location == "rosary-audio"
    assert stockage.querystring_auth is True
    assert not stockage.custom_domain
    url = stockage.url("mystere.mp3")
    assert url.startswith("https://s3.ceac.dev/jangubi-staging/rosary-audio/mystere.mp3?")
    assert "X-Amz-Signature=" in url


@override_settings(
    **S3, MINIO_PUBLIC_URL="", ROSARY_AUDIO_BUCKET="rosary-audio", ROSARY_AUDIO_LOCATION="", ROSARY_AUDIO_PUBLIC=True
)
def test_mode_public_developpement():
    stockage = RosaryAudioStorage()
    assert stockage.querystring_auth is False
    assert stockage.custom_domain == "s3.ceac.dev/rosary-audio"
