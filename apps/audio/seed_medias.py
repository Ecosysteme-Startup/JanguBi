"""Médias des données de test (plan §5, lot S4). Aucun binaire dans Git : on versionne le manifeste.

Sources, par ordre de préférence :

1. **album fourni** (``--medias-dossier``) : pistes libres de l'utilisateur, jamais commitées ; elles
   servent de chants et de musique. Attribution lue dans ``credits.yaml`` (facultatif) du dossier ;
2. **manifeste** ``seed_assets/manifest.yaml`` : compléments du domaine public, CC0 ou CC BY(-SA),
   téléchargés une fois par ``fetch_seed_assets`` (sha256 vérifié) dans le cache local
   (``~/.cache/jangubi-seed/``) ou, en recette, dans le bucket MinIO ``seed-assets`` ;
3. **voix** (homélies, lectures, retraites) : synthèse vocale locale **Piper** si elle est installée ;
   sinon repli **ffmpeg** (signal de parole synthétique : bruit rose filtré et modulé au rythme d'une
   voix). On n'échoue jamais faute de Piper ;
4. **ffmpeg** seul pour la musique quand rien d'autre n'est disponible (accords tenus, type orgue).
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import pathlib
import shutil
import subprocess
import urllib.request
from typing import Any

import yaml
from django.conf import settings

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".wav", ".m4a", ".aac"}
SEED_BUCKET = "seed-assets"


def manifest_path() -> pathlib.Path:
    return pathlib.Path(settings.BASE_DIR) / "seed_assets" / "manifest.yaml"


def cache_dir() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("JANGUBI_SEED_CACHE", "~/.cache/jangubi-seed")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclasses.dataclass
class Asset:
    id: str
    url: str
    licence: str
    auteur: str
    attribution: str
    usage: str  # chant | orgue | pochette
    titre: str = ""
    sha256: str | None = None
    duree: float | None = None
    fichier: str = ""

    @property
    def filename(self) -> str:
        return self.fichier or f"{self.id}{pathlib.Path(self.url).suffix.lower() or '.bin'}"


def load_manifest() -> list[Asset]:
    path = manifest_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fields = {f.name for f in dataclasses.fields(Asset)}
    return [Asset(**{k: v for k, v in item.items() if k in fields}) for item in data.get("fichiers", [])]


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Stockage des médias de test : cache local ou bucket MinIO « seed-assets » ------------------------


class LocalStore:
    kind = "cache local"

    def __init__(self) -> None:
        self.root = cache_dir()

    def has(self, name: str) -> bool:
        return (self.root / name).exists()

    def put(self, name: str, local: pathlib.Path) -> None:
        if local.resolve() != (self.root / name).resolve():
            shutil.copyfile(local, self.root / name)

    def get(self, name: str) -> pathlib.Path | None:
        path = self.root / name
        return path if path.exists() else None


class MinioStore:
    """Bucket ``seed-assets`` du MinIO de recette (partagé ; téléchargé une seule fois)."""

    kind = f"bucket MinIO « {SEED_BUCKET} »"

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3", endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
            aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
            region_name=getattr(settings, "AWS_S3_REGION_NAME", None) or "us-east-1",
        )  # fmt: skip
        try:
            self.client.head_bucket(Bucket=SEED_BUCKET)
        except Exception:  # noqa: BLE001
            self.client.create_bucket(Bucket=SEED_BUCKET)
        self.local = LocalStore()

    def has(self, name: str) -> bool:
        try:
            self.client.head_object(Bucket=SEED_BUCKET, Key=name)
            return True
        except Exception:  # noqa: BLE001
            return False

    def put(self, name: str, local: pathlib.Path) -> None:
        self.client.upload_file(str(local), SEED_BUCKET, name)

    def get(self, name: str) -> pathlib.Path | None:
        cached = self.local.get(name)
        if cached is not None:
            return cached
        if not self.has(name):
            return None
        target = self.local.root / name
        self.client.download_file(SEED_BUCKET, name, str(target))
        return target


def store_for(profil: str) -> LocalStore | MinioStore:
    if profil == "recette" and bool(getattr(settings, "AWS_S3_ACCESS_KEY_ID", None)):
        return MinioStore()
    return LocalStore()


def fetch(asset: Asset, store: Any, *, timeout: int = 60) -> tuple[str, str]:
    """Télécharge ``asset`` s'il manque, vérifie son sha256, le range dans ``store``. Renvoie (état, sha)."""
    if store.has(asset.filename):
        path = store.get(asset.filename)
        digest = sha256_of(path) if path else ""
        if asset.sha256 and digest and digest != asset.sha256:
            return "empreinte différente", digest
        return "déjà présent", digest
    tmp = cache_dir() / f".{asset.filename}.part"
    request = urllib.request.Request(asset.url, headers={"User-Agent": "JanguBi-seed/1.0 (donnees de test)"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(tmp, "wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)
    digest = sha256_of(tmp)
    if asset.sha256 and digest != asset.sha256:
        tmp.unlink(missing_ok=True)
        return "empreinte différente (rejeté)", digest
    final = cache_dir() / asset.filename
    tmp.replace(final)
    store.put(asset.filename, final)
    return "téléchargé", digest


# --- Album fourni par l'utilisateur -----------------------------------------------------------------


@dataclasses.dataclass
class UserTrack:
    path: pathlib.Path
    titre: str
    compositeur: str
    interpretes: list[str]
    credit: str


def user_album(folder: str | None) -> list[UserTrack]:
    """Pistes du dossier (triées), avec l'attribution de ``credits.yaml`` si présent :

    .. code-block:: yaml

        album: {titre: "…", artiste: "…", licence: "CC BY 4.0", source: "https://…"}
        pistes:
          "01-kyrie.mp3": {titre: "Kyrie", compositeur: "…", interpretes: ["…"], attribution: "…"}
    """
    if not folder:
        return []
    root = pathlib.Path(folder).expanduser()
    if not root.is_dir():
        return []
    credits: dict[str, Any] = {}
    for name in ("credits.yaml", "credits.yml"):
        if (root / name).exists():
            credits = yaml.safe_load((root / name).read_text(encoding="utf-8")) or {}
            break
    album = credits.get("album") or {}
    per_track = credits.get("pistes") or {}
    tracks = []
    for path in sorted(p for p in root.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS):
        meta = per_track.get(path.name) or {}
        attribution = meta.get("attribution") or " · ".join(
            x for x in [album.get("artiste", ""), album.get("titre", ""), album.get("licence", ""), album.get("source", "")] if x
        )
        tracks.append(
            UserTrack(
                path=path, titre=meta.get("titre") or path.stem.replace("_", " ").replace("-", " ").strip().capitalize(),
                compositeur=meta.get("compositeur", ""), interpretes=list(meta.get("interpretes") or ([album["artiste"]] if album.get("artiste") else [])),
                credit=attribution or "Album libre fourni pour la recette.",
            )
        )  # fmt: skip
    return tracks


# --- Synthèse -----------------------------------------------------------------------------------------


def _ffmpeg(*args: str) -> None:
    subprocess.run([settings.AUDIO_FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=1800)


def piper_command(voice: str | None) -> list[str] | None:
    """Commande Piper utilisable, ou ``None`` (binaire ou voix absents)."""
    voice = voice or os.environ.get("PIPER_VOICE", "")
    binary = shutil.which(os.environ.get("PIPER_BIN", "piper"))
    if not binary or not voice or not pathlib.Path(voice).expanduser().exists():
        return None
    return [binary, "--model", str(pathlib.Path(voice).expanduser())]


def speech(text: str, out: pathlib.Path, *, seconds: float, voice: str | None, seed: int) -> str:
    """Voix lisant ``text`` (Piper), bouclée ou coupée à ``seconds``. Repli ffmpeg documenté. Renvoie le moteur."""
    cmd = piper_command(voice)
    if cmd is not None:
        raw = out.with_suffix(".piper.wav")
        try:
            subprocess.run([*cmd, "--output_file", str(raw)], input=text.encode(), check=True, timeout=600,
                           capture_output=True)  # fmt: skip
            _ffmpeg("-stream_loop", "-1", "-i", str(raw), "-t", f"{seconds:.1f}", "-ac", "1", "-ar", "22050", str(out))
            raw.unlink(missing_ok=True)
            return "piper"
        except (subprocess.SubprocessError, OSError):
            pass
    # Repli : bruit rose filtré dans la bande de la voix, modulé au rythme des syllabes et des phrases.
    rate = 3.2 + (seed % 7) * 0.15
    _ffmpeg(
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.6:seed={seed}:duration={seconds:.1f}",
        "-af", f"highpass=f=180,lowpass=f=3200,tremolo=f={rate:.2f}:d=0.85,tremolo=f=0.35:d=0.6,volume=1.6",
        "-ac", "1", "-ar", "22050", str(out),
    )  # fmt: skip
    return "ffmpeg"


def music(out: pathlib.Path, *, seconds: float, seed: int) -> None:
    """Accords tenus (type orgue), quand aucune piste libre n'est disponible."""
    roots = [196.0, 220.0, 246.9, 261.6, 293.7]
    f = roots[seed % len(roots)]
    chord = [f, f * 1.25, f * 1.5, f * 2]
    inputs: list[str] = []
    for freq in chord:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={freq:.2f}:duration={seconds:.1f}"]
    _ffmpeg(*inputs, "-filter_complex",
            f"amix=inputs={len(chord)}:normalize=1,tremolo=f=0.2:d=0.3,aecho=0.8:0.7:60:0.3,volume=0.8",
            "-ac", "2", "-ar", "44100", str(out))  # fmt: skip


def excerpt(src: pathlib.Path, out: pathlib.Path, *, seconds: float | None, start: float = 0.0) -> None:
    """Extrait (``--medias legers`` : 30 s) ou copie intégrale réencodée en FLAC."""
    args = ["-ss", f"{start:.1f}", "-i", str(src)]
    if seconds:
        args += ["-t", f"{seconds:.1f}"]
    _ffmpeg(*args, "-vn", "-ac", "2", "-ar", "44100", str(out))
