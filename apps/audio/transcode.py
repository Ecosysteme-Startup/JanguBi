"""Chaîne ffmpeg de la sonothèque (plan §5.2). Fonctions pures sur des fichiers locaux : aucune
base, aucun stockage. ``services.transcode_track`` s'occupe du reste (verrou, version, dépôt).

Étapes : ffprobe (durée, tags) → normalisation EBU R128 (``loudnorm`` à −16 LUFS, un passage) vers
un FLAC intermédiaire → HLS AAC, segments de 6 s, 3 débits → MP3 128 kb/s → forme d'onde (200 pics)
→ ``master.m3u8``.

Débit « bas » : la spécification demande du HE-AAC 32 kb/s mono. L'encodeur HE-AAC de ffmpeg est
``libfdk_aac``, absent des builds distribués (licence non libre). Sans lui, on encode en **AAC-LC
48 kb/s mono** : à 32 kb/s, l'AAC-LC natif de ffmpeg sonne nettement moins bien que le HE-AAC ;
48 kb/s mono reste léger en 2G/3G (≈ 22 Mo par heure). Si ``libfdk_aac`` est présent, on l'utilise.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
from django.conf import settings


class TranscodeError(Exception):
    """Échec technique (ffmpeg, disque) : on peut réessayer."""


class InvalidMediaError(TranscodeError):
    """Le fichier n'est pas un audio lisible, ou dépasse la durée maximale : inutile de réessayer."""


@dataclass(frozen=True)
class RenditionSpec:
    kind: str  # RenditionKind
    folder: str
    bitrate_kbps: int
    channels: int
    codec_args: tuple[str, ...]
    codecs: str  # attribut CODECS du manifeste maître
    codec_label: str


@dataclass
class RenditionResult:
    spec: RenditionSpec
    playlist: str  # chemin relatif au dossier de sortie
    files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    peak_bandwidth: int = 0
    average_bandwidth: int = 0


@dataclass
class TranscodeResult:
    duration_seconds: float
    tags: dict[str, str]
    waveform: list[float]
    renditions: list[RenditionResult]
    mp3: str
    mp3_size: int
    files: list[str]  # tous les fichiers produits, relatifs au dossier de sortie


def _run(args: list[str], *, timeout: int = 3600, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=True, capture_output=capture, timeout=timeout)
    except FileNotFoundError as exc:
        raise TranscodeError(f"Programme introuvable : {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"Délai dépassé : {os.path.basename(args[0])}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip().splitlines()
        raise TranscodeError(stderr[-1] if stderr else f"{os.path.basename(args[0])} a échoué") from exc


@lru_cache(maxsize=4)
def has_encoder(name: str) -> bool:
    try:
        out = _run([settings.AUDIO_FFMPEG_BIN, "-hide_banner", "-encoders"], timeout=30).stdout.decode()
    except TranscodeError:
        return False
    return re.search(rf"^\s*A\S*\s+{re.escape(name)}\s", out, re.MULTILINE) is not None


def rendition_specs() -> list[RenditionSpec]:
    if has_encoder("libfdk_aac"):
        low = RenditionSpec(
            "hls_bas", "bas", 32, 1, ("-c:a", "libfdk_aac", "-profile:a", "aac_he", "-b:a", "32k"), "mp4a.40.5", "HE-AAC"
        )
    else:
        low = RenditionSpec("hls_bas", "bas", 48, 1, ("-c:a", "aac", "-b:a", "48k"), "mp4a.40.2", "AAC-LC")
    return [
        low,
        RenditionSpec("hls_moyen", "moyen", 64, 2, ("-c:a", "aac", "-b:a", "64k"), "mp4a.40.2", "AAC-LC"),
        RenditionSpec("hls_haut", "haut", 128, 2, ("-c:a", "aac", "-b:a", "128k"), "mp4a.40.2", "AAC-LC"),
    ]


def probe(path: str) -> dict[str, Any]:
    """Durée (s), tags (clés en minuscules) et nombre de canaux, lus par ffprobe."""
    try:
        out = _run(
            [settings.AUDIO_FFPROBE_BIN, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            timeout=120,
        ).stdout
    except TranscodeError as exc:
        raise InvalidMediaError(f"Fichier audio illisible ({exc}).") from exc
    data = json.loads(out or b"{}")
    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise InvalidMediaError("Aucune piste audio dans ce fichier.")
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration") or audio[0].get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise InvalidMediaError("Durée de l'enregistrement illisible.")
    if duration > settings.AUDIO_MAX_DURATION_SECONDS:
        raise InvalidMediaError("Enregistrement trop long.")
    tags = {str(k).lower(): str(v)[:500] for k, v in {**audio[0].get("tags", {}), **fmt.get("tags", {})}.items()}
    return {"duration": duration, "tags": tags, "channels": int(audio[0].get("channels") or 2)}


def _ffmpeg() -> list[str]:
    return [settings.AUDIO_FFMPEG_BIN, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]


def normalize(src: str, dst: str) -> None:
    """Normalisation EBU R128 (loudnorm, un passage) vers un FLAC 44,1 kHz stéréo."""
    loudnorm = (
        f"loudnorm=I={settings.AUDIO_LOUDNORM_I}:TP={settings.AUDIO_LOUDNORM_TP}:LRA={settings.AUDIO_LOUDNORM_LRA}"
    )
    _run([*_ffmpeg(), "-i", src, "-map", "0:a:0", "-vn", "-af", loudnorm, "-ar", "44100", "-ac", "2", "-c:a", "flac", dst])


_EXTINF = re.compile(r"#EXTINF:([\d.]+)")


def _bandwidths(out_dir: str, playlist_rel: str) -> tuple[list[str], int, int, int]:
    """Segments d'un manifeste, taille totale, débit crête et moyen (bits/s, conteneur compris)."""
    folder = os.path.dirname(playlist_rel)
    with open(os.path.join(out_dir, playlist_rel)) as fh:
        lines = fh.read().splitlines()
    files: list[str] = []
    total_bytes, total_duration, peak = 0, 0.0, 0
    pending: float | None = None
    for line in lines:
        match = _EXTINF.match(line)
        if match:
            pending = float(match.group(1))
        elif line and not line.startswith("#") and pending is not None:
            rel = os.path.join(folder, line)
            size = os.path.getsize(os.path.join(out_dir, rel))
            files.append(rel)
            total_bytes += size
            total_duration += pending
            if pending > 0:
                peak = max(peak, int(size * 8 / pending))
            pending = None
    average = int(total_bytes * 8 / total_duration) if total_duration else 0
    return files, total_bytes, peak, average


def encode_hls(norm: str, out_dir: str, spec: RenditionSpec) -> RenditionResult:
    folder = os.path.join(out_dir, spec.folder)
    os.makedirs(folder, exist_ok=True)
    playlist_rel = f"{spec.folder}/index.m3u8"
    _run(
        [
            *_ffmpeg(),
            "-i", norm,
            "-vn",
            "-ac", str(spec.channels),
            "-ar", "44100",
            *spec.codec_args,
            "-f", "hls",
            "-hls_time", str(settings.AUDIO_HLS_SEGMENT_SECONDS),
            "-hls_playlist_type", "vod",
            "-hls_list_size", "0",
            "-hls_segment_type", "mpegts",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", os.path.join(folder, "seg_%05d.ts"),
            os.path.join(out_dir, playlist_rel),
        ]
    )  # fmt: skip
    segments, size, peak, average = _bandwidths(out_dir, playlist_rel)
    if not segments:
        raise TranscodeError(f"Aucun segment produit pour {spec.folder}.")
    return RenditionResult(
        spec=spec,
        playlist=playlist_rel,
        files=[playlist_rel, *segments],
        size_bytes=size,
        peak_bandwidth=peak,
        average_bandwidth=average,
    )


def encode_mp3(norm: str, dst: str, *, title: str = "", artist: str = "") -> None:
    args = [*_ffmpeg(), "-i", norm, "-vn", "-c:a", "libmp3lame", "-b:a", "128k", "-ac", "2", "-ar", "44100"]
    args += ["-id3v2_version", "3"]
    if title:
        args += ["-metadata", f"title={title}"]
    if artist:
        args += ["-metadata", f"artist={artist}"]
    _run([*args, dst])


def waveform(norm: str, *, peaks: int | None = None) -> list[float]:
    """``peaks`` pics d'amplitude (0 à 1, le plus haut vaut 1), pour l'animation du lecteur."""
    count = peaks or settings.AUDIO_WAVEFORM_PEAKS
    raw = _run([*_ffmpeg(), "-i", norm, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]).stdout
    samples = np.abs(np.frombuffer(raw, dtype="<i2").astype(np.float32))
    if samples.size == 0:
        return [0.0] * count
    if samples.size < count:
        samples = np.pad(samples, (0, count - samples.size))
    values = np.array([chunk.max() for chunk in np.array_split(samples, count)], dtype=np.float32)
    top = float(values.max())
    if top > 0:
        values = values / top
    return [round(float(v), 3) for v in values]


def master_playlist(renditions: list[RenditionResult]) -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for r in renditions:
        peak = max(r.peak_bandwidth, r.spec.bitrate_kbps * 1000)
        average = max(r.average_bandwidth, 1)
        lines.append(
            f'#EXT-X-STREAM-INF:BANDWIDTH={peak},AVERAGE-BANDWIDTH={average},CODECS="{r.spec.codecs}"'
        )
        lines.append(r.playlist)
    return "\n".join(lines) + "\n"


def transcode(src: str, out_dir: str, *, work_dir: str, title: str = "", artist: str = "") -> TranscodeResult:
    """Chaîne complète. ``out_dir`` reçoit l'arborescence à déposer telle quelle sous
    ``audio-hls/<track_id>/<version>/`` ; ``work_dir`` reçoit les intermédiaires."""
    info = probe(src)
    norm = os.path.join(work_dir, "normalise.flac")
    normalize(src, norm)
    renditions = [encode_hls(norm, out_dir, spec) for spec in rendition_specs()]
    mp3_rel = "audio.mp3"
    encode_mp3(norm, os.path.join(out_dir, mp3_rel), title=title, artist=artist)
    peaks = waveform(norm)
    with open(os.path.join(out_dir, "waveform.json"), "w") as fh:
        json.dump({"version": 1, "peaks": peaks}, fh)
    with open(os.path.join(out_dir, "master.m3u8"), "w") as fh:
        fh.write(master_playlist(renditions))
    files = [f for r in renditions for f in r.files] + [mp3_rel, "waveform.json", "master.m3u8"]
    return TranscodeResult(
        duration_seconds=round(info["duration"], 3),
        tags=info["tags"],
        waveform=peaks,
        renditions=renditions,
        mp3=mp3_rel,
        mp3_size=os.path.getsize(os.path.join(out_dir, mp3_rel)),
        files=files,
    )
