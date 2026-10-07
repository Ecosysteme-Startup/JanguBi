import asyncio
import logging
from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Based on AELF guidelines, limiting concurrency
CONCURRENCY = 6
semaphore = asyncio.Semaphore(CONCURRENCY)

# Standard base endpoint
AELF_BASE_URL = "https://api.aelf.org"

# Headers reflecting identity
HEADERS = {"User-Agent": "JanguBi/1.0 (contact@jangubi.org)"}


class AelfApiError(Exception):
    """Custom exception when AELF API returns unexpected or persistent errors."""

    pass


def is_retryable_error(exception):
    """
    We want to retry on 429 (Too Many Requests) or 5xx server errors,
    but NOT on 404 (Not Found) or 400 (Bad Request).
    """
    if isinstance(exception, httpx.HTTPStatusError):
        # Retry on 429 and any 500+
        return exception.response.status_code == 429 or exception.response.status_code >= 500
    # Retry on transport errors (Network failure, Timeout)
    return isinstance(exception, (httpx.RequestError, httpx.TimeoutException))


class AelfAsyncClient:
    """
    Asynchronous client for interacting with the AELF API.
    Handles rate-limiting, backoff retries, and concurrent connections safe-guarding.
    """

    @classmethod
    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _fetch(cls, client: httpx.AsyncClient, endpoint: str) -> Dict[str, Any]:
        """
        Core fetch logic with configured Semaphore for concurrency
        and Tenacity wrapping for transient errors/rate-limits.
        """
        url = f"{AELF_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        async with semaphore:
            try:
                response = await client.get(url, timeout=15.0)
                # If the status code indicates an error, raise HTTPStatusError
                response.raise_for_status()
                return response.json()
            except Exception as e:
                # Custom logging before the Tenacity retry catches it
                if is_retryable_error(e):
                    logger.warning(f"Transient error fetching {url}. Retrying... ({str(e)})")
                    raise  # triggers @retry

                # If it's a 4xx error (like 404), do not retry, just evaluate
                if isinstance(e, httpx.HTTPStatusError):
                    logger.info(f"Non-retryable HTTP error {e.response.status_code} on {url}: {e.response.text}")
                    # Return empty to allow processing to continue gracefully (e.g. no office on a given date)
                    return {}

                logger.error(f"Fatal error fetching {url}: {str(e)}")
                raise AelfApiError(f"Failed to fetch {url}: {str(e)}")

    @classmethod
    async def get_informations(cls, date_str: str, zone: str = "romain") -> Dict[str, Any]:
        async with httpx.AsyncClient(headers=HEADERS) as client:
            return await cls._fetch(client, f"/v1/informations/{date_str}/{zone}")

    @classmethod
    async def get_mass(cls, date_str: str, zone: str = "romain") -> Dict[str, Any]:
        async with httpx.AsyncClient(headers=HEADERS) as client:
            return await cls._fetch(client, f"/v1/messes/{date_str}/{zone}")

    @classmethod
    async def get_office(cls, office_name: str, date_str: str, zone: str = "romain") -> Dict[str, Any]:
        """
        office_name: 'laudes', 'vepres', 'tierce', 'sexte', 'none', 'complies', 'lectures'
        """
        async with httpx.AsyncClient(headers=HEADERS) as client:
            return await cls._fetch(client, f"/v1/{office_name}/{date_str}/{zone}")

    @classmethod
    async def fetch_all_daily(cls, date_str: str, zone: str = "romain") -> Dict[str, Dict[str, Any]]:
        """
        Concurrency helper: fetch informations, mass, and all major offices at once.
        """
        endpoints = {
            "informations": f"/v1/informations/{date_str}/{zone}",
            "messes": f"/v1/messes/{date_str}/{zone}",
            "lectures": f"/v1/lectures/{date_str}/{zone}",  # Office des lectures
            "laudes": f"/v1/laudes/{date_str}/{zone}",
            "tierce": f"/v1/tierce/{date_str}/{zone}",
            "sexte": f"/v1/sexte/{date_str}/{zone}",
            "none": f"/v1/none/{date_str}/{zone}",
            "vepres": f"/v1/vepres/{date_str}/{zone}",
            "complies": f"/v1/complies/{date_str}/{zone}",
        }

        results: Dict[str, Dict[str, Any]] = {}
        async with httpx.AsyncClient(headers=HEADERS) as client:
            # Create list of tasks
            keys = list(endpoints.keys())
            tasks = [cls._fetch(client, endpoints[k]) for k in keys]

            # Execute concurrently
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for key, response in zip(keys, responses):
                if isinstance(response, BaseException):
                    logger.error(f"Error fetching {key} concurrently: {str(response)}")
                    results[key] = {}
                else:
                    results[key] = response

        return results
