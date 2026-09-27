from django.conf import settings

from apps.donations.providers.base import PaymentProvider, ProviderError


def get_provider(code: str | None = None) -> PaymentProvider:
    """Agrégateur ``code`` (défaut : ``DONATIONS_PROVIDER``)."""
    code = code or settings.DONATIONS_PROVIDER
    if code == "fake":
        from apps.donations.providers.fake import FakeProvider

        return FakeProvider()
    if code == "paydunya":
        from apps.donations.providers.paydunya import PayDunyaProvider

        return PayDunyaProvider()
    raise ProviderError(f"Agrégateur inconnu : {code!r}.")


def known_provider(code: str) -> bool:
    return code in {"fake", "paydunya"}
