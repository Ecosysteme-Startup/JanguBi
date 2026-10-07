import logging
from typing import Any, Dict

from asgiref.sync import sync_to_async

from apps.liturgy.client import AelfAsyncClient
from apps.liturgy.matcher import CitationMatcher
from apps.liturgy.models import AelfDataEntry, AelfResource, LiturgicalDate, Office, Reading

logger = logging.getLogger(__name__)


class AelfService:
    """
    Coordinates fetching from the AELF HTTP Client and saving to the Django ORM.
    Handles idempotent Database writes.
    """

    @staticmethod
    @sync_to_async
    def _save_raw(endpoint: str, dt_str: str, zone: str, raw_json: Dict[str, Any]) -> None:
        """Saves the unadulterated response for audit tracking."""
        AelfDataEntry.objects.create(source_endpoint=endpoint, date=dt_str, zone=zone, raw_json=raw_json)

    @staticmethod
    @sync_to_async
    def _get_or_create_liturgical_date(dt_str: str, zone: str, info_data: Dict[str, Any]) -> LiturgicalDate:
        """Parses the /informations endpoint dict into the local LiturgicalDate model."""
        info = info_data.get("informations", {})
        ld, _ = LiturgicalDate.objects.update_or_create(
            date=dt_str,
            zone=zone,
            defaults={
                "day_name": info.get("jour") or "",
                "season": info.get("temps") or "",
                "mystery": info.get("fete") or "",
                "notes": info.get("couleur") or "",
            },
        )
        return ld

    @staticmethod
    @sync_to_async
    def _save_resources(ld: LiturgicalDate, info_data: Dict[str, Any]) -> None:
        """Parses mp3/youtube links from informations response."""
        info = info_data.get("informations", {})
        audio_url = info.get("audio") or info.get("mp3") or None
        yt_url = info.get("youtube") or info.get("video") or None

        if audio_url or yt_url:
            AelfResource.objects.update_or_create(
                liturgical_date=ld,
                defaults={
                    "audio_url": audio_url,
                    "youtube_url": yt_url,
                },
            )

    @staticmethod
    @sync_to_async
    def _save_readings(ld: LiturgicalDate, source_json: Dict[str, Any]) -> None:
        """
        Parses readings from the messes/lectures payload.
        e.g., {"messes": [{"lectures": [{"type": "lecture1", "ref": "...", "contenu": "..."}]}]}
        """
        # AELF JSON differs based on endpoint. Usually "messes" is a list.
        messes = source_json.get("messes", [])
        if not messes:
            return

        # Target the first mass if multiple are returned
        primary_mass = messes[0]
        lectures = primary_mass.get("lectures", [])

        for lec in lectures:
            typ = lec.get("type", "unknown")
            ref = lec.get("ref", "")
            texte = lec.get("contenu", "")

            # Create the Reading
            reading, created = Reading.objects.update_or_create(
                liturgical_date=ld, type=typ, citation=ref, defaults={"text": texte, "raw_metadata": lec}
            )

            # If it's a new or updated reading, attempt to match to local Bible
            # Matcher relies on sync_to_async, but we are already inside a sync_to_async block.
            # However `CitationMatcher.match` is marked async, so we must be careful.
            # Actually, let's call it synchronously inside this sync block.

    @staticmethod
    @sync_to_async
    def _save_readings_sync(ld: LiturgicalDate, source_json: Dict[str, Any]):
        # Synchronous internal mapping layer
        messes = source_json.get("messes", [])
        if not messes:
            return

        primary_mass = messes[0]
        lectures = primary_mass.get("lectures", [])

        for lec in lectures:
            typ = lec.get("type", "unknown")
            ref = lec.get("ref", "")
            texte = lec.get("contenu", "")

            # Use synchronous matching BEFORE creating the object to avoid
            # holding the transaction open too long locally if CitationMatcher gets heavy
            verses = CitationMatcher.match(ref)

            reading, _ = Reading.objects.update_or_create(
                liturgical_date=ld, type=typ, citation=ref, defaults={"text": texte, "raw_metadata": lec}
            )

            if verses:
                reading.matched_verses.set(verses)

    @staticmethod
    @sync_to_async
    def _save_office_sync(ld: LiturgicalDate, office_type: str, office_json: Dict[str, Any]):
        """Parses Laudes, Vepres etc. payloads with high accuracy for AELF structure."""
        data = office_json.get(office_type, office_json)
        if not data:
            return

        # 1. Extract Hymn (often a dict with "texte")
        hymne_data = data.get("hymne")
        hymn_text = ""
        if isinstance(hymne_data, dict):
            hymn_text = hymne_data.get("texte", "")
        elif isinstance(hymne_data, str):
            hymn_text = hymne_data

        # 2. Consolidate Psalms
        psalms = []
        for i in range(1, 4):
            ps_key = f"psaume_{i}"
            ant_key = f"antienne_{i}"
            if ps_key in data or ant_key in data:
                psalms.append({"number": i, "antienne": data.get(ant_key, ""), "psaume": data.get(ps_key, {})})

        # 3. Extract Canticle based on office
        canticle_text = ""
        canticle_keys = {"laudes": "cantique_zacharie", "vepres": "cantique_mariale", "complies": "cantique_symeon"}
        c_key = canticle_keys.get(office_type)
        if c_key and c_key in data:
            c_data = data.get(c_key)
            if isinstance(c_data, dict):
                canticle_text = c_data.get("texte", "")
            else:
                canticle_text = str(c_data)

        # 4. Extract Readings/Pericope
        readings = []
        if office_type == "lectures":
            # For Office of Readings, we have two main blocks
            if "lecture" in data:
                readings.append(data["lecture"])
            if "texte_patristique" in data:
                readings.append(
                    {
                        "titre": data.get("titre_patristique", "Texte Patristique"),
                        "texte": data.get("texte_patristique"),
                        "repons": data.get("repons_patristique"),
                    }
                )
        else:
            # For others, it's usually "pericope"
            pericope = data.get("pericope")
            if pericope:
                readings = [pericope] if not isinstance(pericope, list) else pericope

        # 5. Extract Intercessions
        intercession = data.get("intercession", "")

        Office.objects.update_or_create(
            liturgical_date=ld,
            office_type=office_type,
            defaults={
                "hymn": hymn_text,
                "psalms": psalms,
                "canticle": canticle_text,
                "readings": readings,
                "intercessions": str(intercession),
                "raw_metadata": data,
            },
        )

    @classmethod
    async def sync_daily_data(cls, date_str: str, zone: str = "afrique") -> None:
        """
        Orchestrates fetching ALL daily endpoints concurrently,
        then synchronously saving them to the DB.
        """
        logger.info(f"Syncing AELF data for {date_str} ({zone})")

        # 1. Fetch concurrently
        payloads = await AelfAsyncClient.fetch_all_daily(date_str, zone)

        # 2. Informational data is required to anchor LiturgicalDate
        info_json = payloads.get("informations", {})
        if not info_json:
            logger.warning("Could not fetch /informations, aborting daily sync.")
            return

        # Save Raw JSONs
        for key, payload in payloads.items():
            if payload:
                await cls._save_raw(f"/v1/{key}", date_str, zone, payload)

        # 3. Create LiturgicalDate context
        ld = await cls._get_or_create_liturgical_date(date_str, zone, info_json)
        await cls._save_resources(ld, info_json)

        # 4. Map Masses/Lectures
        if "messes" in payloads and payloads["messes"]:
            await cls._save_readings_sync(ld, payloads["messes"])

        # 5. Map Offices
        office_types = ["laudes", "tierce", "sexte", "none", "vepres", "complies", "lectures"]
        for ot in office_types:
            if ot in payloads and payloads[ot]:
                await cls._save_office_sync(ld, ot, payloads[ot])

        logger.info(f"Successfully synced AELF data for {date_str}")


def readings_link_verses(*, only_missing: bool = True) -> int:
    """Rattache chaque lecture aux versets de la Bible locale d'après sa référence.

    À relancer après un import (ou un réimport) de la Bible : le lien est posé à l'import AELF et
    disparaît quand les versets sont supprimés. Renvoie le nombre de lectures rattachées.
    """
    from django.db import transaction

    CitationMatcher._books_cache = None
    linked = 0
    readings = Reading.objects.exclude(citation="")
    if only_missing:
        readings = readings.filter(matched_verses__isnull=True)
    with transaction.atomic():
        for reading in readings.distinct().iterator():
            verses = CitationMatcher.match(reading.citation)
            if verses:
                reading.matched_verses.set(verses)
                linked += 1
    return linked
