"""Semeurs de la Parole (``seed_realiste``, lot S5).

La Bible et les lectures sont de **vraies données** : rien n'est généré. ``bible`` appelle l'import réel
(``import_bible`` avec le JSON fourni par ``--bible-json``) si la Bible est absente, puis l'indexation
(tsvector, embeddings) comme les tâches de l'import ; ``liturgie`` appelle la synchronisation AELF réelle
(``AelfService.sync_daily_data``, celle de la tâche ``daily_sync``) pour la semaine, avec repli sans
réseau (étape sautée et signalée). ``parole`` sème seulement l'activité des lecteurs (lectures sur
90 jours par profils, signets, surlignages) ; ``parole_reco`` recalcule « Pour vous »
(``bible_reco_recompute_task``).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import uuid
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.db import transaction

from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register

EVENT_PREFIX = "seed-"
GOSPELS = ("matthieu", "marc", "luc", "jean")


def bible_present() -> bool:
    """Une Bible est-elle là, même partielle ? Suffit pour semer de l'activité de lecture ; ne suffit PAS
    pour décider d'importer (voir ``bible_complete``)."""
    from apps.bible.models import Verse

    return Verse.objects.exists()


def bible_complete(json_path: str | pathlib.Path, source: str) -> bool:
    """Chaque livre du fichier a-t-il des versets de cette source en base ?

    L'import est atomique PAR LIVRE : une interruption laisse des livres entiers manquants, jamais des
    versets épars. On compte donc les livres, pas les versets — l'importeur fusionne des entrées du
    fichier (doublons, noms rapprochés : 35 407 entrées pour 35 283 versets en AELF), un compte de
    versets se tromperait. Fichier illisible : repli sur ``bible_present`` plutôt que de déclencher un
    réimport, qui supprime d'abord tous les versets de la source (et les signets qui s'y rattachent).
    """
    from apps.bible.models import Book

    try:
        expected = len(json.loads(pathlib.Path(json_path).read_text(encoding="utf-8-sig"))["books"])
    except (OSError, ValueError, KeyError, TypeError):
        return bible_present()
    found = Book.objects.filter(chapters__verses__source_file=source).distinct().count()
    return found >= expected


@register
class BibleSeeder(Seeder):
    name = "bible"
    module = "parole"
    phase = Phase.HIERARCHIE
    always = True  # rien n'est créé par le lot : vérifie ou importe à chaque passage

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        if bible_complete(ctx.bible_json, ctx.bible_source) if ctx.bible_json else bible_present():
            return {"bible": "déjà importée"}
        if not ctx.bible_json:
            ctx.note("Bible absente et --bible-json non fourni : l'activité de lecture est sautée "
                     "(ex. --bible-json init/bibles/format/json/bible-fr-aelf.json).")  # fmt: skip
            return {"bible": "absente"}
        call_command("import_bible", ctx.bible_json, source=ctx.bible_source, verbosity=0)
        from apps.bible.models import Book
        from apps.bible.tasks import compute_embeddings_task, populate_tsv_task

        # Les tâches d'indexation de l'import sont retenues pendant le semis : on les exécute ici.
        for book_id in Book.objects.values_list("pk", flat=True):
            populate_tsv_task.apply(args=[book_id])
            if getattr(settings, "PGVECTOR_ENABLED", False):
                compute_embeddings_task.apply(args=[book_id])
        return {"bible": f"importée depuis {ctx.bible_json} ({ctx.bible_source})"}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.bible.models import Verse

        n = Verse.objects.count()
        return [Check("Bible (données réelles)", True, f"{n} versets" if n else "absente : --bible-json non fourni, lecture sautée")]


def aelf_reachable(day: datetime.date, zone: str, timeout: float = 5.0) -> bool:
    """Sonde rapide (une requête, sans les nouvelles tentatives du client) : évite d'attendre les
    délais de la synchronisation quand AELF est injoignable ou refuse la connexion."""
    import httpx

    from apps.liturgy.client import AELF_BASE_URL

    try:
        response = httpx.get(f"{AELF_BASE_URL}/v1/informations/{day.isoformat()}/{zone}", timeout=timeout)
    except (httpx.HTTPError, OSError):
        return False
    return response.status_code == 200


@register
class LiturgieSeeder(Seeder):
    name = "liturgie"
    module = "parole"
    phase = Phase.HIERARCHIE
    always = True

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from asgiref.sync import async_to_sync

        from apps.liturgy.models import LiturgicalDate
        from apps.liturgy.services import AelfService

        days = [ctx.today + datetime.timedelta(days=i) for i in range(-1, 8)]
        zone = settings.LITURGY_ZONE
        missing = [d for d in days if not LiturgicalDate.objects.filter(date=d, zone=zone).exists()]
        if not missing:
            return {"lectures": "déjà synchronisées"}
        if not ctx.reseau or not aelf_reachable(ctx.today, zone):
            ctx.note(f"AELF injoignable : lectures non synchronisées pour {len(missing)} jour(s) (repli : "
                     "« lecture du jour » tirée des évangiles). Relancer plus tard ou `import_aelf`.")  # fmt: skip
            return {"lectures": "repli sans réseau"}
        for day in missing:
            try:
                async_to_sync(AelfService.sync_daily_data)(day.isoformat(), zone)
            except Exception as exc:  # noqa: BLE001 - une journée en erreur n'arrête pas le semis
                ctx.note(f"AELF {day} : {exc.__class__.__name__}")
        synced = LiturgicalDate.objects.filter(date__in=missing, zone=zone).count()
        if synced < len(missing):
            ctx.note(f"AELF : {len(missing) - synced} jour(s) non synchronisé(s) (repli : lecture tirée des évangiles).")
        return {"jours_synchronises": synced}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.liturgy.models import LiturgicalDate

        ok = LiturgicalDate.objects.filter(date=ctx.today, zone=settings.LITURGY_ZONE).exists()
        return [Check("Lectures du jour (AELF)", True, "synchronisées" if ok else "absentes (repli sans réseau, non bloquant)")]


def _gospel_chapters() -> list[Any]:
    from apps.bible.models import Chapter

    chapters = []
    for name in GOSPELS:
        chapters += list(Chapter.objects.filter(book__slug__icontains=name).order_by("book__order", "number"))
    if not chapters:  # autre nommage des livres : Nouveau Testament
        chapters = list(Chapter.objects.filter(book__testament__slug__icontains="nouveau").order_by("book__order", "number")[:89])
    return chapters or list(Chapter.objects.order_by("book__order", "number")[:100])


def _daily_chapter(day: datetime.date, fallback: list[Any]) -> Any:
    from apps.liturgy.models import Reading

    reading = (
        Reading.objects.filter(liturgical_date__date=day, liturgical_date__zone=settings.LITURGY_ZONE, type__icontains="evangile")
        .prefetch_related("matched_verses__chapter")
        .first()
    )
    if reading is not None:
        verse = reading.matched_verses.first()
        if verse is not None:
            return verse.chapter
    return fallback[day.toordinal() % len(fallback)]


@register
class ParoleSeeder(Seeder):
    name = "parole"
    module = "parole"
    phase = Phase.PAROLE
    depends = ("bible", "liturgie", "appartenances")

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.bible.models import Bookmark, Chapter, ReadingEvent, Verse

        if not bible_present():
            return {"lectures": "sautées (Bible absente)"}
        rng = ctx.rng(self.name)
        gospels = _gospel_chapters()
        psalms = list(Chapter.objects.filter(book__slug__icontains="psaume").order_by("number")) or gospels
        everything = list(Chapter.objects.values_list("pk", flat=True))
        fideles = list(ctx.fideles_qs().order_by("pk").values_list("pk", flat=True))
        readers = rng.sample(fideles, k=min(len(fideles), ctx.scale.lecteurs_parole))
        readers += [p.pk for p in (ctx.persona("fidele"), ctx.persona("fidele2")) if p]
        daily = {d: _daily_chapter(d, gospels) for d in (ctx.today - datetime.timedelta(days=i) for i in range(90))}
        events, bookmarks = [], []
        chapter_ids_read: dict[Any, list[Any]] = {}
        for uid in readers:
            profile = rng.choices(["quotidien", "continu", "occasionnel"], [40, 25, 35])[0]
            cursor = rng.randrange(len(gospels))
            read: list[Any] = []
            for back in range(90, -1, -1):
                day = ctx.today - datetime.timedelta(days=back)
                if profile == "quotidien" and rng.random() < 0.7:
                    chapters = [daily.get(day) or gospels[day.toordinal() % len(gospels)]]
                elif profile == "continu" and rng.random() < 0.55:
                    chapters = [gospels[cursor % len(gospels)]]
                    cursor += 1
                elif profile == "occasionnel" and rng.random() < 0.18:
                    chapters = [rng.choice(psalms) if rng.random() < 0.4 else rng.choice(gospels)]
                    if rng.random() < 0.2:
                        chapters.append(Chapter(pk=rng.choice(everything)))
                else:
                    continue
                for ch in chapters:
                    at = ctx.aware(day, rng.choice([6, 7, 12, 21, 22]), rng.randint(0, 59))
                    if at > ctx.now:
                        at = ctx.now - datetime.timedelta(minutes=5)
                    events.append(ReadingEvent(user_id=uid, client_event_id=f"{EVENT_PREFIX}{uuid.UUID(int=rng.getrandbits(128))}",
                                               kind="lu", chapter_id=ch.pk, finished=rng.random() < 0.7, occurred_at=at))  # fmt: skip
                    read.append(ch.pk)
            chapter_ids_read[uid] = read
        # Signets et surlignages sur des versets des chapitres lus.
        verses_by_chapter: dict[Any, list[Any]] = {}
        wanted = {c for ids in chapter_ids_read.values() for c in ids}
        for vid, cid in Verse.objects.filter(chapter_id__in=wanted).values_list("pk", "chapter_id"):
            verses_by_chapter.setdefault(cid, []).append(vid)
        colors = [c for c in Bookmark.Color.values if c]
        seen: set[tuple[Any, Any]] = set()
        for uid, ids in chapter_ids_read.items():
            if not ids or rng.random() > 0.35:
                continue
            for _ in range(rng.randint(1, 5)):
                cid = rng.choice(ids)
                if not verses_by_chapter.get(cid):
                    continue
                vid = rng.choice(verses_by_chapter[cid])
                if (uid, vid) in seen:
                    continue
                seen.add((uid, vid))
                highlight = rng.random() < 0.5
                bookmarks.append(Bookmark(user_id=uid, verse_id=vid, color=rng.choice(colors) if highlight else ""))
                events.append(ReadingEvent(user_id=uid, client_event_id=f"{EVENT_PREFIX}{uuid.UUID(int=rng.getrandbits(128))}",
                                           kind="surligne" if highlight else "signet", chapter_id=cid, verse_start_id=vid,
                                           occurred_at=ctx.now - datetime.timedelta(days=rng.randint(0, 60))))  # fmt: skip
        with transaction.atomic():
            ReadingEvent.objects.bulk_create(events, batch_size=5000, ignore_conflicts=True)
            Bookmark.objects.bulk_create(bookmarks, batch_size=5000, ignore_conflicts=True)
            ctx.track(Bookmark, [b.pk for b in bookmarks if b.pk])
        return {"lecteurs": len(readers), "lectures": len(events), "signets": len(bookmarks)}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.bible.models import Bookmark, ReadingEvent

        n, _ = ReadingEvent.objects.filter(client_event_id__startswith=EVENT_PREFIX).delete()
        ctx.tracked(Bookmark).delete()
        return {"lectures": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.bible.models import ReadingEvent

        if not bible_present():
            return [Check("Activité de lecture", True, "sautée : Bible absente")]
        n = ReadingEvent.objects.filter(client_event_id__startswith=EVENT_PREFIX).count()
        return [Check("Activité de lecture sur 90 jours", n > 0, f"{n} signaux de lecture")]


@register
class ParoleRecoSeeder(Seeder):
    name = "parole_reco"
    module = "parole"
    phase = Phase.RECALCULS
    depends = ("parole",)
    always = True

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        if not bible_present():
            return {"recommandations": "sautées (Bible absente)"}
        from apps.bible.services.recommendation_service import daily_recommendations_recompute

        result = daily_recommendations_recompute()
        if not result.get("stored") and not _real_embeddings():
            ctx.note("« Pour vous » (Parole) vide : EMBEDDING_PROVIDER=stub (vecteurs nuls). En recette : "
                     "EMBEDDING_PROVIDER=local, `seed_embeddings`, puis relancer seed_realiste --modules parole.")  # fmt: skip
        return result

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.bible.models import DailyRecommendation

        if not bible_present():
            return [Check("« Pour vous » (Parole) calculé", True, "sauté : Bible absente")]
        n = DailyRecommendation.objects.filter(date=ctx.today).count()
        if n == 0 and not _real_embeddings():
            return [Check("« Pour vous » (Parole) calculé", True,
                          "non calculable : versets sans embeddings réels (EMBEDDING_PROVIDER=local puis seed_embeddings)")]  # fmt: skip
        return [Check("« Pour vous » (Parole) calculé", n > 0, f"{n} fidèles avec une recommandation du jour")]


def _real_embeddings() -> bool:
    """Le moteur « Pour vous » compare des vecteurs : il faut des embeddings réels (le fournisseur
    ``stub`` des tests et du poste local produit des vecteurs nuls)."""
    return getattr(settings, "EMBEDDING_PROVIDER", "stub") != "stub"
