import asyncio
import logging
from datetime import date
from typing import Dict, List, Optional

import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from apps.bible.models import DailyText
from apps.bible.services.cleaning import CleaningService
from apps.bible.services.search_service import SearchService

logger = logging.getLogger(__name__)


class AELFService:
    """Service to fetch and process daily readings from the AELF API."""

    def __init__(self):
        self.base_url = getattr(settings, "AELF_API_BASE", "https://api.aelf.org/v1/messes")
        self.search_service = SearchService()

    async def fetch_daily_readings(self, target_date: Optional[date] = None) -> List[DailyText]:
        """
        Fetches the readings for a specific date (defaults to today).
        Retries with exponential backoff if the API fails.
        """
        if not target_date:
            target_date = timezone.localdate()

        date_str = target_date.strftime("%Y-%m-%d")
        url = f"{self.base_url}/{date_str}/france"

        data = await self._fetch_with_retries(url)
        if not data:
            return []

        return await self._process_api_response(target_date, data)

    async def _fetch_with_retries(self, url: str) -> Optional[Dict]:
        max_retries = 5
        base_delay = 1.0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(max_retries):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPError as e:
                    logger.warning(f"AELF fetch failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2**attempt))
                    else:
                        logger.error(f"AELF fetch completely failed after {max_retries} attempts.")
                        return None
        return None

    @sync_to_async
    def _process_api_response(self, target_date: date, data: Dict) -> List[DailyText]:
        messes = data.get("messes", [])
        if not messes:
            return []

        # Typically, we just care about the first 'messe' of the day for standard readings
        lectures = messes[0].get("lectures", [])
        created_records = []

        for lecture in lectures:
            category = lecture.get("type", "lecture")
            # AELF renvoie parfois « titre »/« contenu » à null (clé présente, valeur
            # null) — ex. psaume sans titre. `.get(k, "")` rendrait None → colonnes
            # NOT NULL → IntegrityError (BUG-B2). On coalesce vers "".
            title = lecture.get("titre") or ""
            raw_content = lecture.get("contenu") or ""

            # Clean HTML and formatting
            clean_content = CleaningService.clean_text(raw_content)

            # Use the search service to find local cross-references if possible
            # We use a very basic title match or skip for now if it's too broad
            local_matches = []
            if title:
                # E.g. "Lecture du livre de la Genèse (Gn 1, 1-19)"
                # Recherche plein texte sur un extrait (ADR-018 : pas de recherche vectorielle)
                snippet = clean_content[:150]
                try:
                    results = self.search_service.search(query=snippet, limit=5)
                    if results and results[0]["matches"]:
                        best_match = results[0]["matches"][0]
                        if best_match["score"] > 0.4:  # reasonable confidence
                            local_matches.append(best_match)
                except Exception as e:
                    logger.warning(f"Failed finding cross-references: {e}")

            # Save to DB
            dt, created = DailyText.objects.update_or_create(
                date=target_date,
                category=category,
                defaults={
                    "title": title,
                    "content": clean_content,
                    "local_matches": local_matches,
                    "source_url": "https://aelf.org",
                },
            )
            created_records.append(dt)

        logger.info(f"Processed {len(created_records)} daily readings for {target_date}")
        return created_records
