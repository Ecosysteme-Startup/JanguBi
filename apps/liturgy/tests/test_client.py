from unittest.mock import patch

import pytest
import respx
from httpx import Response

from apps.liturgy.client import AelfAsyncClient

# Make sure pytest-asyncio runs these
pytestmark = pytest.mark.asyncio


@respx.mock
async def test_get_informations_success():
    """Test standard 200 OK response from AELF."""
    respx.get("https://api.aelf.org/v1/informations/2026-03-01/romain").mock(
        return_value=Response(200, json={"informations": {"jour": "Dimanche", "temps": "Careme"}})
    )

    data = await AelfAsyncClient.get_informations("2026-03-01")
    assert "informations" in data
    assert data["informations"]["jour"] == "Dimanche"


@respx.mock
async def test_get_office_404_graceful_handling():
    """Test that a 404 (e.g. no office on this date) returns an empty dict instead of crashing."""
    respx.get("https://api.aelf.org/v1/laudes/2026-03-01/romain").mock(return_value=Response(404, text="Not Found"))

    data = await AelfAsyncClient.get_office("laudes", "2026-03-01")
    assert data == {}


@respx.mock
async def test_retry_on_429():
    """Test that a 429 Too Many Requests triggers a retry and eventually succeeds."""
    route = respx.get("https://api.aelf.org/v1/messes/2026-03-01/romain")
    route.side_effect = [Response(429, text="Too Many Requests"), Response(200, json={"messes": [{"lectures": []}]})]

    # We mock tenacity's sleep explicitly to speed up the test
    with patch("tenacity.nap.time.sleep", return_value=None):
        data = await AelfAsyncClient.get_mass("2026-03-01")

    assert "messes" in data
    assert route.call_count == 2


@respx.mock
async def test_retry_on_500_failure():
    """Test that repeated 500s eventually raise the custom AelfApiError."""
    route = respx.get("https://api.aelf.org/v1/informations/1999-01-01/romain")
    route.side_effect = [Response(500, text="Internal Server Error")] * 6  # Exceeds max retries

    with patch("tenacity.nap.time.sleep", return_value=None):
        with pytest.raises(Exception):
            await AelfAsyncClient.get_informations("1999-01-01")

    assert route.call_count == 5  # stop_after_attempt(5)
