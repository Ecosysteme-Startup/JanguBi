"""Semeurs de la sonothèque (``seed_realiste``, lots S4 et S5).

- ``sonotheque`` : sources (paroisses, chorales, mouvements), albums (messes, homélies, retraites, chants
  à Marie), pistes avec visibilités variées, pochettes générées, et médias selon ``--medias`` :
  ``aucun`` (pistes sans fichier, écrans seulement), ``legers`` (extraits de 30 s encodés directement par
  la chaîne réelle ``transcode``, une fois par extrait, puis déposés pour chaque piste) ou ``complets``
  (fichiers entiers passés par le **vrai pipeline** : fichier source, file ``media``, HLS, forme d'onde) ;
- ``ecoutes`` : événements d'écoute sur 13 mois (table partitionnée, ``COPY``) par profils d'auditeurs
  (matin, soir, dimanche, homélies en 1,25×), passes, écoutes complètes, likes, playlists, reprises,
  signalements ;
- ``audio_reco`` : recalcul des recommandations (``recompute_all``, comme ``audio_reco_recompute_task``).
"""

from __future__ import annotations

import datetime
import itertools
import math
import pathlib
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from typing import Any

from django.conf import settings
from django.db import connection, transaction

from apps.core.seeding import bulk, images, textes
from apps.core.seeding.context import DEVICE_ID, SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.core.seeding.world import CHORALES, MOUVEMENTS
from apps.hierarchy.seeders import staff_of

VOICE_KINDS = {"homelie", "lecture", "retraite", "enseignement"}
LATIN = ("Kyrie", "Gloria", "Sanctus", "Agnus", "Ave", "Salve", "Magnificat", "Ubi", "Regina", "Victimae", "Adeste",
         "Veni", "Tantum", "Jubilate", "Laudate")  # fmt: skip
N_CHORALES = {"petite": 2, "moyenne": 5, "grande": 6}
N_MOUVEMENTS = {"petite": 1, "moyenne": 3, "grande": 4}


def _season(day: datetime.date) -> str:
    from apps.liturgy.calendar import liturgical_day

    try:
        return liturgical_day(day).season
    except Exception:  # noqa: BLE001
        return "ordinaire"


class MediaFactory:
    """Prépare les médias une fois par variante et les rattache aux pistes selon ``--medias``."""

    def __init__(self, ctx: SeedContext) -> None:
        from apps.audio import seed_medias

        self.ctx = ctx
        self.m = seed_medias
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="jangubi-seed-"))
        self.seconds = 30.0 if ctx.medias == "legers" else None
        self._music: list[dict[str, Any]] | None = None
        self._voice: list[dict[str, Any]] | None = None
        self._encoded: dict[str, Any] = {}
        self._raw: dict[str, Any] = {}
        self.engines: Counter[str] = Counter()

    # Variantes ---------------------------------------------------------------------------------------

    def _metadata_only(self, kind: str) -> list[dict[str, Any]]:
        """``aucun`` : aucune synthèse, seulement des titres et des crédits."""
        credit = "Pas de fichier (--medias aucun) : piste de test pour les écrans."
        if kind == "voix":
            return [{"key": f"voix-{i}", "path": None, "titre": h["titre"], "compositeur": "", "interpretes": [],
                     "credit": credit, "moteur": "aucun"} for i, h in enumerate(textes()["homelies"])]  # fmt: skip
        return [{"key": f"chant-{i}", "path": None, "titre": "", "compositeur": "", "interpretes": [], "credit": credit,
                 "moteur": "aucun"} for i in range(4)]  # fmt: skip

    def music(self) -> list[dict[str, Any]]:
        if self._music is not None:
            return self._music
        if self.ctx.medias == "aucun":
            self._music = self._metadata_only("musique")
            return self._music
        out: list[dict[str, Any]] = []
        album = self.m.user_album(self.ctx.medias_dossier)
        if self.ctx.medias_dossier and not album:
            self.ctx.note(f"--medias-dossier {self.ctx.medias_dossier} : aucun fichier audio lu, repli sur les autres sources.")
        limit = 4 if self.ctx.medias == "legers" else 40
        for i, t in enumerate(album[:limit]):
            dst = self.tmp / f"album-{i}.flac"
            try:
                self.m.excerpt(t.path, dst, seconds=self.seconds, start=15.0 if self.seconds else 0.0)
            except Exception:  # noqa: BLE001 - piste trop courte : depuis le début
                self.m.excerpt(t.path, dst, seconds=self.seconds)
            out.append({"key": f"album-{i}", "path": dst, "titre": t.titre, "compositeur": t.compositeur,
                        "interpretes": t.interpretes, "credit": t.credit, "moteur": "album"})  # fmt: skip
        if album:
            self.engines["album fourni"] += len(out)
        store = self.m.store_for(self.ctx.profil) if self.ctx.profil == "recette" else self.m.LocalStore()
        for asset in [a for a in self.m.load_manifest() if a.usage in ("chant", "orgue")]:
            path = store.get(asset.filename)
            if path is None:
                continue
            dst = self.tmp / f"{asset.id}.flac"
            self.m.excerpt(path, dst, seconds=self.seconds)
            out.append({"key": asset.id, "path": dst, "titre": asset.titre, "compositeur": "", "interpretes": [asset.auteur],
                        "credit": f"{asset.attribution} ({asset.licence})", "moteur": "manifeste"})  # fmt: skip
            self.engines["manifeste"] += 1
        if not out:
            for i in range(3):
                dst = self.tmp / f"synth-{i}.flac"
                self.m.music(dst, seconds=self.seconds or 180.0 + 40 * i, seed=self.ctx.graine + i)
                out.append({"key": f"synth-{i}", "path": dst, "titre": "", "compositeur": "", "interpretes": [],
                            "credit": "Accords synthétiques (ffmpeg), données de test.", "moteur": "ffmpeg"})  # fmt: skip
            self.engines["musique ffmpeg"] += 3
            self.ctx.note("Musique : ni album fourni ni fichier du manifeste en cache, accords synthétiques ffmpeg.")
        self._music = out
        return out

    def voice(self) -> list[dict[str, Any]]:
        if self._voice is not None:
            return self._voice
        if self.ctx.medias == "aucun":
            self._voice = self._metadata_only("voix")
            return self._voice
        rng = self.ctx.rng("voix")
        out = []
        texts = textes()["homelies"]
        for i, h in enumerate(texts[: 3 if self.ctx.medias == "legers" else 6]):
            dst = self.tmp / f"voix-{i}.flac"
            seconds = self.seconds or float(rng.randint(8, 25) * 60)
            engine = self.m.speech(h["texte"], dst, seconds=seconds, voice=self.ctx.piper_voix, seed=self.ctx.graine + i)
            credit = (
                "Voix de synthèse Piper (voix sous licence libre) lisant un texte rédigé pour le projet."
                if engine == "piper"
                else "Signal de voix synthétique (ffmpeg, repli sans Piper), données de test."
            )
            out.append({"key": f"voix-{i}", "path": dst, "titre": h["titre"], "compositeur": "", "interpretes": [],
                        "credit": credit, "moteur": engine})  # fmt: skip
            self.engines[f"voix {engine}"] += 1
        if out and out[0]["moteur"] == "ffmpeg":
            self.ctx.note("Piper indisponible (binaire ou voix absents) : voix de repli ffmpeg. Voir docs/DONNEES-DE-TEST.md.")
        self._voice = out
        return out

    # Rattachement ------------------------------------------------------------------------------------

    def _raw_file(self, variant: dict[str, Any], uploader: Any) -> Any:
        from apps.audio import storage
        from apps.files.models import File
        from apps.files.utils import file_generate_name

        stored = file_generate_name(f"{variant['key']}.flac")
        key = f"{settings.AUDIO_RAW_PREFIX}/{stored}"
        storage.put_file(key=key, local_path=str(variant["path"]))
        raw = File(original_file_name=f"{variant['key']}.flac", file_name=stored, file_type="audio/flac",
                   uploaded_by=uploader, upload_finished_at=self.ctx.now)  # fmt: skip
        raw.file.name = key
        raw.save()
        self.ctx.track(File, [raw.pk])
        return raw

    def attach_light(self, track: Any, variant: dict[str, Any]) -> None:
        """``legers`` : encodage réel une fois par extrait, dépôt pour chaque piste (``_mark_ready``)."""
        from apps.audio import storage, transcode
        from apps.audio.models import TrackRendition
        from apps.audio.services import hls_prefix

        key = variant["key"]
        if key not in self._encoded:
            out, work = self.tmp / f"out-{key}", self.tmp / f"work-{key}"
            out.mkdir()
            work.mkdir()
            result = transcode.transcode(str(variant["path"]), str(out), work_dir=str(work), title=variant["titre"])
            self._encoded[key] = (out, result)
            self._raw[key] = self._raw_file(variant, track.uploaded_by)
        out, result = self._encoded[key]
        prefix = hls_prefix(track.pk, 1)
        for rel in result.files:
            storage.put_file(key=f"{prefix}/{rel}", local_path=str(out / rel))
        rows = [
            TrackRendition(track=track, version=1, kind=r.spec.kind, codec=r.spec.codec_label, bitrate_kbps=r.spec.bitrate_kbps,
                           channels=r.spec.channels, path=f"{prefix}/{r.playlist}", size_bytes=r.size_bytes)
            for r in result.renditions
        ] + [TrackRendition(track=track, version=1, kind="mp3", codec="MP3", bitrate_kbps=128, channels=2,
                            path=f"{prefix}/{result.mp3}", size_bytes=result.mp3_size)]  # fmt: skip
        TrackRendition.objects.bulk_create(rows)
        track.raw_file = self._raw[key]
        track.status, track.version, track.encoded_version = "pret", 1, 1
        track.encoded_at, track.encoding_step, track.encoding_percent = self.ctx.now, "termine", 100
        track.duration_seconds, track.probe_tags, track.waveform = result.duration_seconds, result.tags, result.waveform

    def attach_full(self, track: Any, variant: dict[str, Any]) -> None:
        """``complets`` : fichier source déposé, piste ``en_file`` ; l'encodage part sur la file ``media``."""
        track.raw_file = self._raw_file(variant, track.uploaded_by)
        track.status, track.version = "en_file", 1

    @staticmethod
    def attach_none(track: Any, rng: Any) -> None:
        """``aucun`` : pistes sans fichier (écrans seulement), rendus fictifs pour la forme."""
        from apps.audio.models import TrackRendition
        from apps.audio.services import hls_prefix

        prefix = hls_prefix(track.pk, 1)
        TrackRendition.objects.bulk_create(
            [TrackRendition(track=track, version=1, kind=k, codec=c, bitrate_kbps=b, channels=ch, path=f"{prefix}/{p}")
             for k, c, b, ch, p in [("hls_bas", "AAC-LC", 48, 1, "bas/index.m3u8"), ("hls_moyen", "AAC-LC", 64, 2, "moyen/index.m3u8"),
                                    ("hls_haut", "AAC-LC", 128, 2, "haut/index.m3u8"), ("mp3", "MP3", 128, 2, "piste.mp3")]]
        )  # fmt: skip
        track.status, track.version, track.encoded_version = "pret", 1, 1
        track.encoded_at, track.encoding_step, track.encoding_percent = timezone_now(), "termine", 100
        peaks = [round(abs(math.sin(i / 7.0)) * 0.6 + rng.random() * 0.4, 3) for i in range(200)]
        track.waveform = peaks

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


def timezone_now() -> datetime.datetime:
    from django.utils import timezone

    return timezone.now()


@register
class SonothequeSeeder(Seeder):
    name = "sonotheque"
    module = "audio"
    phase = Phase.AUDIO
    depends = ("appartenances",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.audio.models import Album, AudioSource, Track
        from apps.audio.services import track_search_index

        rng = ctx.rng(self.name)
        parishes = ctx.parishes()
        t = textes()
        sources: list[tuple[Any, Any]] = []  # (source, publisher)
        with transaction.atomic():
            for i, parish in enumerate(parishes):
                cure = staff_of(parish, "cure")
                sources.append((AudioSource.objects.create(
                    node=parish, kind="paroisse", name=parish.name, created_by=cure,
                    description="Messes, homélies et temps forts de la paroisse."), cure))  # fmt: skip
            for i, (name, description) in enumerate(CHORALES[: N_CHORALES[ctx.scale.code]]):
                parish = parishes[i % len(parishes)]
                sources.append((AudioSource.objects.create(node=parish, kind="chorale", name=name, description=description,
                                                           created_by=staff_of(parish, "cure")), staff_of(parish, "cure")))  # fmt: skip
            for i, (name, description) in enumerate(MOUVEMENTS[: N_MOUVEMENTS[ctx.scale.code]]):
                parish = parishes[(i + 1) % len(parishes)]
                sources.append((AudioSource.objects.create(node=parish, kind="mouvement", name=name, description=description,
                                                           created_by=staff_of(parish, "cure")), staff_of(parish, "cure")))  # fmt: skip
            ctx.track(AudioSource, [s.pk for s, _ in sources])
            covers = self._covers(ctx, sources)

        # Plan des albums jusqu'au nombre de pistes de l'échelle.
        plan: list[dict[str, Any]] = []
        total, k = 0, 0
        while total < ctx.scale.pistes:
            source, publisher = sources[k % len(sources)]
            voice: bool | None
            recorded = ctx.today - datetime.timedelta(days=rng.randint(5, 360))
            if source.kind == "chorale":
                kind, title, n, voice = "album", rng.choice(["Chants à Marie", "Messe des anges", "Chants de Noël",
                                                               "Louange et action de grâce", "Veillée pascale"]), rng.randint(6, 12), False  # fmt: skip
            elif source.kind == "mouvement":
                kind, title, n, voice = rng.choice([("retraite", "Retraite spirituelle", rng.randint(3, 6), True),
                                                    ("album", "Chapelet médité", rng.randint(4, 6), False)])  # fmt: skip
            else:
                kind = rng.choice(["messe", "homelies", "homelies", "retraite"])
                title = {"messe": f"Messe du {recorded:%d/%m/%Y}", "homelies": "Homélies du dimanche",
                         "retraite": "Retraite paroissiale"}[kind]  # fmt: skip
                n = rng.randint(5, 8) if kind == "messe" else rng.randint(4, 9)
                voice = None if kind == "messe" else True  # messe : lectures et homélie parlées, le reste chanté
            n = min(n, ctx.scale.pistes - total)
            vis = rng.choices(["public", "paroisse", "prive"], [70, 20, 10])[0]
            plan.append({"source": source, "publisher": publisher, "kind": kind, "title": f"{title} {recorded.year}" if kind != "messe" else title,
                         "n": n, "voice": voice, "recorded": recorded, "visibility": vis})  # fmt: skip
            total += n
            k += 1

        media = MediaFactory(ctx)
        tracks_created: list[Any] = []
        albums: list[Any] = []
        chants = t["chants"]
        try:
            for a_index, item in enumerate(plan):
                source = item["source"]
                season = _season(item["recorded"])
                published = None if item["visibility"] == "prive" else ctx.aware(item["recorded"] + datetime.timedelta(days=2), 10)
                with transaction.atomic():
                    album = Album.objects.create(
                        source=source, kind=item["kind"], title=item["title"], visibility=item["visibility"],
                        description=f"{item['title']} — {source.name}.", recorded_on=item["recorded"], liturgical_season=season,
                        published_at=published, created_by=item["publisher"], cover=covers.get(source.pk),
                    )  # fmt: skip
                    albums.append(album)
                    for pos in range(item["n"]):
                        voice = item["voice"] if item["voice"] is not None else pos in (2, 3)
                        variants = media.voice() if voice else media.music()
                        variant = variants[(a_index + pos) % len(variants)]
                        if voice:
                            title = variant["titre"] if item["kind"] != "messe" else ["Lectures", "Homélie"][pos - 2]
                            if item["kind"] == "homelies":
                                sunday = item["recorded"] - datetime.timedelta(days=7 * pos)
                                title = f"Homélie du dimanche {sunday:%d/%m/%Y}"
                        else:
                            title = variant["titre"] or chants[(a_index * 3 + pos) % len(chants)]
                        latin = title.startswith(LATIN)
                        track_vis = "paroisse" if rng.random() < 0.08 else "public"
                        track = Track(
                            id=uuid.UUID(int=rng.getrandbits(128), version=4), source=source, album=album, position=pos + 1,
                            title=title[:250], performers=variant["interpretes"] or [source.name],
                            composer=variant["compositeur"] or ("Grégorien" if latin else ("" if voice else "Traditionnel")),
                            language="la" if latin else "fr", liturgical_season=season,
                            tags=(["homélie", "parole"] if voice else ["chant", "marial" if "Marie" in item["title"] or "Ave" in title else "liturgie"]),
                            description=f"Crédits : {variant['credit']}", visibility=track_vis,
                            effective_visibility=_most_restrictive(track_vis, item["visibility"]),
                            published_at=published, uploaded_by=item["publisher"], rights_confirmed_at=ctx.now,
                            duration_seconds=_duration(rng, voice, item["kind"]),
                        )  # fmt: skip
                        if ctx.medias == "aucun":
                            media.attach_none(track, rng)
                        elif ctx.medias == "legers":
                            media.attach_light(track, variant)
                        else:
                            media.attach_full(track, variant)
                        track.save(force_insert=True)
                        tracks_created.append(track)
                    ctx.track(Album, [album.pk])
        finally:
            media.cleanup()
        track_search_index(track_ids=[tr.pk for tr in tracks_created])
        dispatched = self._dispatch(ctx, [tr for tr in tracks_created if tr.status == "en_file"])
        from apps.audio.services import catalog_invalidate

        catalog_invalidate()
        return {"sources": len(sources), "albums": len(albums), "pistes": len(tracks_created),
                "medias": ", ".join(f"{k} {v}" for k, v in media.engines.items()) or ctx.medias,
                **({"encodages_lances": dispatched} if dispatched else {})}  # fmt: skip

    def _covers(self, ctx: SeedContext, sources: list[tuple[Any, Any]]) -> dict[Any, Any]:
        from apps.audio import seed_medias
        from apps.audio.models import AudioSource
        from apps.files.models import File

        store = seed_medias.store_for(ctx.profil) if ctx.profil == "recette" else seed_medias.LocalStore()
        photos: list[tuple[Any, pathlib.Path]] = []
        for asset in seed_medias.load_manifest():
            found = store.get(asset.filename) if asset.usage == "pochette" else None
            if found is not None:
                photos.append((asset, found))
        out = {}
        for i, (source, publisher) in enumerate(sources):
            subtitle = {"paroisse": "Paroisse", "chorale": "Chorale", "mouvement": "Mouvement"}[source.kind]
            if source.kind == "chorale" and photos:
                asset, path = photos[i % len(photos)]
                f = images.stored_file(name=asset.filename, content_type="image/jpeg", uploaded_by=publisher,
                                       content=path.read_bytes(),
                                       key=f"{settings.AUDIO_COVER_PREFIX}/seed/{source.pk}/{asset.filename}")  # fmt: skip
                AudioSource.objects.filter(pk=source.pk).update(
                    cover=f, description=f"{source.description} Pochette : {asset.attribution} ({asset.licence})."
                )
                out[source.pk] = f
                continue
            f = images.stored_file(
                name="pochette.png", content_type="image/png", uploaded_by=publisher,
                content=images.cover_png(title=source.name.removeprefix("Paroisse "), subtitle=subtitle, index=i, size=480),
                key=f"{settings.AUDIO_COVER_PREFIX}/seed/{source.pk}/pochette.png",
            )  # fmt: skip
            AudioSource.objects.filter(pk=source.pk).update(cover=f)
            out[source.pk] = f
        ctx.track(File, [f.pk for f in out.values()])
        return out

    def _dispatch(self, ctx: SeedContext, tracks: list[Any]) -> int:
        """``complets`` : encodage par la file ``media`` si un courtier répond, sinon en direct (noté)."""
        if not tracks:
            return 0
        from apps.audio.services import transcode_track
        from apps.audio.tasks import audio_transcode_task

        try:
            from celery import current_app

            with current_app.connection_for_write() as conn:
                conn.ensure_connection(max_retries=1, timeout=3)
            for tr in tracks:
                audio_transcode_task.apply_async(args=[str(tr.pk), tr.version], retry=False)
            ctx.note(f"{len(tracks)} encodage(s) envoyé(s) sur la file « media » (le worker celery-media les traite).")
        except Exception:  # noqa: BLE001 - pas de courtier : encodage direct, même service
            for tr in tracks:
                transcode_track(track_id=tr.pk, version=tr.version)
            ctx.note(f"Aucun courtier Celery joignable : {len(tracks)} piste(s) encodée(s) en direct par transcode_track.")
        return len(tracks)

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.audio import storage
        from apps.audio.models import AudioSource, Track
        from apps.files.models import File

        tracks = Track.objects.filter(source__in=ctx.tracked(AudioSource))
        for track_id in tracks.values_list("pk", flat=True):
            try:
                storage.delete_prefix(prefix=f"{settings.AUDIO_HLS_PREFIX}/{track_id}/")
            except Exception:  # noqa: BLE001
                pass
        n = tracks.count()
        ctx.tracked(AudioSource).delete()
        for f in ctx.tracked(File, self.name):
            try:
                if f.file:
                    f.file.storage.delete(f.file.name)
            except Exception:  # noqa: BLE001
                pass
            f.delete()
        from apps.audio.services import catalog_invalidate

        catalog_invalidate()
        return {"pistes": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from django.db.models import Count, Q

        from apps.audio.models import AudioSource, Track

        if ctx.medias == "complets":
            self._wait_encoded(ctx)
        tracks = Track.objects.filter(source__in=ctx.tracked(AudioSource))
        total = tracks.count()
        ready = tracks.filter(status="pret").count()
        three = (
            tracks.filter(status="pret")
            .annotate(n=Count("renditions", filter=Q(renditions__kind__startswith="hls_")))
            .filter(n=3)
            .count()
        )
        checks = [Check("Pistes à l'état « pret » avec leurs 3 débits", total > 0 and ready == total == three,
                        f"{total} pistes, {ready} prêtes, {three} avec 3 débits HLS")]  # fmt: skip
        if ctx.medias != "aucun" and ready:
            from apps.audio import storage

            first = tracks.filter(status="pret").first()
            sample = first.renditions.filter(kind="hls_moyen").first() if first else None
            present = sample is not None and storage.head(key=sample.path) is not None
            checks.append(Check("Fichiers HLS présents dans le stockage", present, sample.path if sample else "aucun rendu"))
        return checks

    @staticmethod
    def _wait_encoded(ctx: SeedContext, timeout: int = 1800) -> None:
        from apps.audio.models import AudioSource, Track

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = Track.objects.filter(source__in=ctx.tracked(AudioSource), status__in=["en_file", "encodage"]).count()
            if not pending:
                return
            ctx.log(f"encodage en cours : {pending} piste(s) restantes…")
            time.sleep(10)


def _most_restrictive(*values: str) -> str:
    from apps.audio.enums import most_restrictive

    return most_restrictive(*values)


def _duration(rng: Any, voice: bool, kind: str) -> float:
    if voice:
        return float(rng.randint(480, 1500) if kind in ("homelies", "retraite", "messe") else rng.randint(120, 300))
    return float(rng.randint(150, 400))


# --- Écoutes ---------------------------------------------------------------------------------------

PROFILES = {
    "matin": ([6, 7, 8], 0.2),
    "soir": ([20, 21, 22], 0.2),
    "dimanche": ([9, 10, 11, 16, 17], 0.65),
    "homelies": ([7, 12, 19, 21], 0.35),
}


class _EventBuffer(list):  # type: ignore[type-arg]
    """Événements d'écoute écrits par ``COPY`` au fil de l'eau (5 M à l'échelle grande : pas tout en mémoire)."""

    COLUMNS = ["occurred_at", "received_at", "client_event_id", "user_id", "track_id", "kind", "position_seconds", "device_id"]
    LIMIT = 200_000

    def __init__(self) -> None:
        super().__init__()
        self.written = 0

    def append(self, row: Any) -> None:
        super().append(row)
        if len(self) >= self.LIMIT:
            self.flush()

    def __len__(self) -> int:
        return self.written + super().__len__()

    def flush(self) -> int:
        pending = list(self[:])
        if pending:
            self.written += bulk.copy_rows("audio_play_event", self.COLUMNS, pending)
            del self[:]
        return self.written


def _month_start(day: datetime.date, shift: int = 0) -> datetime.date:
    index = day.year * 12 + (day.month - 1) + shift
    return datetime.date(index // 12, index % 12 + 1, 1)


def ensure_past_partitions(start: datetime.date, today: datetime.date) -> list[str]:
    """Partitions mensuelles de ``audio_play_event`` depuis ``start`` (la tâche n'en crée que d'avance)."""
    from apps.audio.services import play_event_partitions_ensure

    created = []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audio_play_event'"
        )
        existing = {r[0] for r in cursor.fetchall()}
        month = start.replace(day=1)
        while month < _month_start(today):
            name = f"audio_play_event_p{month:%Y%m}"
            if name not in existing:
                cursor.execute(f'CREATE TABLE "{name}" PARTITION OF audio_play_event FOR VALUES FROM (%s) TO (%s)',
                               [month, _month_start(month, 1)])  # fmt: skip
                created.append(name)
            month = _month_start(month, 1)
    play_event_partitions_ensure(today=today)
    return created


@register
class EcoutesSeeder(Seeder):
    name = "ecoutes"
    module = "audio"
    phase = Phase.ACTIVITE
    depends = ("sonotheque",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.audio.models import (
            AudioSource,
            Like,
            ListenerSettings,
            PlaybackPosition,
            PlaybackState,
            Playlist,
            PlaylistItem,
            Track,
            TrackReport,
        )
        from apps.hierarchy.models import ParishMembership

        rng = ctx.rng(self.name)
        start = max(ctx.start, _month_start(ctx.today, -12))
        created_parts = ensure_past_partitions(start, ctx.today)
        tracks = list(
            Track.objects.filter(source__in=ctx.tracked(AudioSource), status="pret", published_at__isnull=False,
                                 hidden_at__isnull=True).select_related("source").order_by("album_id", "position")
        )  # fmt: skip
        if not tracks:
            return {"evenements": 0}
        by_album: dict[Any, list[Any]] = defaultdict(list)
        for tr in tracks:
            by_album[tr.album_id].append(tr)
        public = [tr for tr in tracks if tr.effective_visibility == "public"]
        popularity = [1.0 / (1 + i) ** 0.8 for i in range(len(tracks))]
        rng.shuffle(popularity)
        pop = {tr.pk: popularity[i] for i, tr in enumerate(tracks)}
        allowed_cache: dict[frozenset[Any], tuple[list[Any], set[Any], list[float]]] = {}
        by_source: dict[Any, list[Any]] = defaultdict(list)
        for tr in tracks:
            by_source[tr.source_id].append(tr)
        memberships: dict[Any, set[Any]] = defaultdict(set)
        for uid, nid in ParishMembership.objects.filter(removed_by_parish_at__isnull=True).values_list("user_id", "node_id"):
            memberships[uid].add(nid)
        fideles = list(ctx.fideles_qs().filter(last_seen_at__isnull=False).order_by("pk").values_list("pk", flat=True))
        listeners = [u for u in fideles if rng.random() < 0.6]
        listeners += [p.pk for p in (ctx.persona("fidele"), ctx.persona("fidele2"), ctx.persona("cure")) if p]
        per_listener = max(3, ctx.scale.ecoutes // max(1, len(listeners)))

        span_days = max(1, (ctx.now - ctx.aware(start, 0)).days)
        events = _EventBuffer()
        completes: Counter[tuple[Any, Any]] = Counter()
        last_play: dict[Any, tuple[Any, float, datetime.datetime]] = {}
        budget = ctx.scale.ecoutes
        for idx, uid in enumerate(listeners + [None] * max(1, len(listeners) // 10)):
            if len(events) >= budget:
                break
            key = frozenset(memberships.get(uid, ())) if uid is not None else frozenset({"anonyme"})
            if key not in allowed_cache:
                subset = public if uid is None else [
                    tr for tr in tracks if tr.effective_visibility == "public" or tr.source.node_id in key
                ]  # fmt: skip
                cum = list(itertools.accumulate(pop[tr.pk] for tr in subset))
                allowed_cache[key] = (subset, {tr.pk for tr in subset}, cum)
            allowed, allowed_ids, cum_weights = allowed_cache[key]
            if not allowed:
                continue
            profile = rng.choice(list(PROFILES))
            hours, sunday_share = PROFILES[profile]
            favs = {tr.source_id for tr in rng.sample(allowed, k=min(len(allowed), rng.randint(1, 3)))}
            fav_tracks = [tr for sid in sorted(favs, key=str) for tr in by_source[sid] if tr.pk in allowed_ids] or allowed
            target = int(per_listener * rng.paretovariate(2.5) / 1.6) + 2
            produced = 0
            while produced < target and len(events) < budget:
                recent_bias = rng.random() ** 0.6  # plus d'écoutes récentes
                day = ctx.today - datetime.timedelta(days=int((1 - recent_bias) * span_days))
                if rng.random() < sunday_share:
                    day -= datetime.timedelta(days=(day.weekday() + 1) % 7)
                if day < start:
                    day = start
                at = ctx.aware(day, rng.choice(hours), rng.randint(0, 59), rng.randint(0, 59))
                if at >= ctx.now:
                    at = ctx.now - datetime.timedelta(minutes=rng.randint(10, 3000))
                current = rng.choice(fav_tracks) if rng.random() < 0.75 else rng.choices(allowed, cum_weights=cum_weights)[0]
                for _ in range(rng.choices([1, 2, 3, 4, 6], [30, 25, 20, 15, 10])[0]):
                    duration = current.duration_seconds or 180.0
                    speed = 1.25 if profile == "homelies" and "homélie" in current.tags else 1.0
                    ev = str(uuid.UUID(int=rng.getrandbits(128), version=4))
                    events.append((at, at + datetime.timedelta(seconds=rng.randint(1, 30)), ev, uid, current.pk, "start", 0.0, DEVICE_ID))
                    r = rng.random()
                    if r < 0.22:  # passée avant 30 s
                        pos = float(rng.randint(3, 28))
                        events.append((at + datetime.timedelta(seconds=pos / speed), at + datetime.timedelta(seconds=pos / speed + 2),
                                       str(uuid.UUID(int=rng.getrandbits(128), version=4)), uid, current.pk, "skip", pos, DEVICE_ID))  # fmt: skip
                        listened = pos / speed
                    else:
                        half = duration / 2
                        events.append((at + datetime.timedelta(seconds=half / speed), at + datetime.timedelta(seconds=half / speed + 2),
                                       str(uuid.UUID(int=rng.getrandbits(128), version=4)), uid, current.pk, "progress", half, DEVICE_ID))  # fmt: skip
                        if r < 0.75:
                            events.append((at + datetime.timedelta(seconds=duration / speed), at + datetime.timedelta(seconds=duration / speed + 2),
                                           str(uuid.UUID(int=rng.getrandbits(128), version=4)), uid, current.pk, "complete", duration, DEVICE_ID))  # fmt: skip
                            completes[(uid, current.pk)] += 1
                            listened = duration / speed
                        else:
                            listened = half / speed
                    if uid is not None and (uid not in last_play or last_play[uid][2] < at):
                        last_play[uid] = (current.pk, min(listened * speed, duration), at)
                    produced += 1
                    at = at + datetime.timedelta(seconds=listened + rng.randint(2, 20))
                    if at >= ctx.now:
                        break
                    siblings = by_album.get(current.album_id, [])
                    nxt = siblings.index(current) + 1 if current in siblings else len(siblings)
                    if rng.random() < 0.6 and nxt < len(siblings) and siblings[nxt].pk in allowed_ids:
                        current = siblings[nxt]
                    else:
                        current = rng.choice(fav_tracks)
            if idx % 2000 == 0 and idx:
                ctx.log(f"écoutes : {len(events)} événements…")

        likes = []
        for (uid, tid), n in completes.items():
            if uid is not None and rng.random() < min(0.8, 0.25 * n):
                likes.append(Like(user_id=uid, track_id=tid))
                events.append((ctx.now - datetime.timedelta(days=rng.randint(0, 80)), ctx.now, str(uuid.UUID(int=rng.getrandbits(128), version=4)),
                               uid, tid, "like", 0.0, DEVICE_ID))  # fmt: skip
        with transaction.atomic():
            n_events = events.flush()
            Like.objects.bulk_create(likes, batch_size=5000, ignore_conflicts=True)
            # Compteurs dénormalisés.
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE audio_track t SET play_count = s.n FROM (SELECT track_id, count(*) AS n FROM audio_play_event "
                    "WHERE kind = 'start' AND device_id = %s GROUP BY track_id) s WHERE s.track_id = t.id",
                    [DEVICE_ID],
                )
                cursor.execute(
                    "UPDATE audio_track t SET like_count = s.n FROM (SELECT track_id, count(*) AS n FROM audio_like "
                    "GROUP BY track_id) s WHERE s.track_id = t.id AND t.id = ANY(%s::uuid[])",
                    [[str(tr.pk) for tr in tracks]],
                )
            playlists, items = [], []
            liked_by: dict[Any, list[Any]] = defaultdict(list)
            for like in likes:
                liked_by[like.user_id].append(like.track_id)
            for uid, tids in liked_by.items():
                if len(tids) >= 3 and rng.random() < 0.4:
                    p = Playlist(owner_id=uid, title=rng.choice(["Pour prier le matin", "Chants à Marie", "Homélies à réécouter",
                                                                  "Pour la route", "Mes chants préférés"]),
                                 visibility="public" if rng.random() < 0.2 else "prive")  # fmt: skip
                    playlists.append(p)
                    items += [PlaylistItem(playlist=p, track_id=tid, position=i + 1) for i, tid in enumerate(tids[:10])]
            sources = list(ctx.tracked(AudioSource))
            for source in sources:
                mine = [tr for tr in tracks if tr.source_id == source.pk and tr.effective_visibility == "public"]
                if len(mine) >= 3:
                    p = Playlist(source=source, title=f"Sélection de {source.name}"[:200], visibility="public",
                                 published_at=ctx.now - datetime.timedelta(days=20), description="Choisis par l'équipe.")  # fmt: skip
                    playlists.append(p)
                    items += [PlaylistItem(playlist=p, track_id=tr.pk, position=i + 1) for i, tr in enumerate(rng.sample(mine, k=min(8, len(mine))))]
            Playlist.objects.bulk_create(playlists)
            PlaylistItem.objects.bulk_create(items, ignore_conflicts=True)
            ctx.track(Playlist, [p.pk for p in playlists if p.owner_id])
            states = [PlaybackState(user_id=u, track_id=t_, position_seconds=pos, device_id=DEVICE_ID, client_updated_at=at)
                      for u, (t_, pos, at) in last_play.items()]  # fmt: skip
            PlaybackState.objects.bulk_create(states, batch_size=5000, ignore_conflicts=True)
            positions = [PlaybackPosition(user_id=u, track_id=t_, position_seconds=pos, device_id=DEVICE_ID, client_updated_at=at)
                         for u, (t_, pos, at) in last_play.items()]  # fmt: skip
            PlaybackPosition.objects.bulk_create(positions, batch_size=5000, ignore_conflicts=True)
            opted = [ListenerSettings(user_id=u, recommendations_enabled=False) for u in listeners[:: 37] if u]
            ListenerSettings.objects.bulk_create(opted, ignore_conflicts=True)
            reports = []
            if len(tracks) >= 3 and listeners:
                for reason, comment in [("qualite", "Le son sature au début de la piste."), ("droits", "Enregistrement d'une autre chorale ?"),
                                        ("autre", "Titre incorrect.")]:  # fmt: skip
                    reports.append(TrackReport(track=rng.choice(tracks), reporter_id=rng.choice(listeners), reason=reason, comment=comment))
                reports[-1].status, reports[-1].handled_at = "rejete", ctx.now - datetime.timedelta(days=2)
                TrackReport.objects.bulk_create(reports)
        return {"evenements": n_events, "auditeurs": len(listeners), "likes": len(likes), "playlists": len(playlists),
                "partitions_creees": len(created_parts)}  # fmt: skip

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.audio.models import Playlist

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audio_play_event WHERE device_id = %s", [DEVICE_ID])
            n = cursor.rowcount
        ctx.tracked(Playlist).delete()
        return {"evenements": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*), min(occurred_at), max(occurred_at) FROM audio_play_event WHERE device_id = %s", [DEVICE_ID])
            n, first, last = cursor.fetchone()
            cursor.execute("SELECT count(*) FROM audio_play_event_default WHERE device_id = %s", [DEVICE_ID])
            default = cursor.fetchone()[0]
        span = f"du {first:%d/%m/%Y} au {last:%d/%m/%Y}" if first else ""
        return [Check("Événements d'écoute rangés dans les partitions mensuelles", n > 0 and default == 0,
                      f"{n} événements {span}, {default} dans la partition par défaut")]  # fmt: skip


@register
class AudioRecoSeeder(Seeder):
    name = "audio_reco"
    module = "audio"
    phase = Phase.RECALCULS
    depends = ("ecoutes",)
    always = True

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.audio.recommendations import recompute_all

        result = recompute_all()
        return {k: v for k, v in result.items()}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.audio.models import TrackNeighbor, UserRecommendation

        users = UserRecommendation.objects.values("user_id").distinct().count()
        neighbors = TrackNeighbor.objects.count()
        return [Check("Recommandations audio calculées", users > 0 and neighbors > 0,
                      f"{users} auditeurs avec « Pour vous », {neighbors} voisins de pistes")]  # fmt: skip
