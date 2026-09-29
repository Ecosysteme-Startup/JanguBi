"""Fichiers générés (plan §5) : pochettes à monogramme (Pillow) et pièces jointes « SPÉCIMEN » (PDF par
reportlab, JPEG par Pillow). Aucune photo de personne réelle."""

from __future__ import annotations

import io
from typing import Any

from django.core.files.base import ContentFile
from django.utils import timezone

SPECIMEN = "SPÉCIMEN — données fictives"
PALETTE = ["#7A2E3A", "#2F4858", "#8C6A2F", "#3E5C45", "#5B4A7A", "#9A4E2A", "#2E5E7A", "#6B3A5A"]


def stored_file(*, name: str, content: bytes, content_type: str, key: str | None = None, uploaded_by: Any = None) -> Any:
    """Crée un ``files.File`` valide (``upload_finished_at``) dont le contenu est dans le stockage par défaut."""
    from apps.files.models import File
    from apps.files.utils import file_generate_name

    stored = file_generate_name(name)
    f = File(original_file_name=name, file_name=stored, file_type=content_type, uploaded_by=uploaded_by)
    if key:
        from django.core.files.storage import default_storage

        default_storage.save(key, ContentFile(content))
        f.file.name = key
    else:
        f.file.save(stored, ContentFile(content), save=False)
    f.upload_finished_at = timezone.now()
    f.save()
    return f


def _font(size: int) -> Any:
    from PIL import ImageFont

    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def cover_png(*, title: str, subtitle: str = "", index: int = 0, size: int = 600) -> bytes:
    """Pochette carrée : couleur de la source, monogramme, titre."""
    from PIL import Image, ImageDraw

    color = PALETTE[index % len(PALETTE)]
    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    initials = "".join(w[0] for w in title.replace("-", " ").split() if w[:1].isalpha() and w[0].isupper())[:2] or "JB"
    draw.ellipse((size * 0.25, size * 0.18, size * 0.75, size * 0.68), outline="#F4EFE6", width=max(2, size // 90))
    font = _font(size // 5)
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(((size - (box[2] - box[0])) / 2, size * 0.43 - (box[3] - box[1]) / 2 - box[1]), initials,
              fill="#F4EFE6", font=font)  # fmt: skip
    small = _font(size // 22)
    for i, line in enumerate([title[:34], subtitle[:40]]):
        if line:
            b = draw.textbbox((0, 0), line, font=small)
            draw.text(((size - (b[2] - b[0])) / 2, size * (0.76 + 0.07 * i)), line, fill="#F4EFE6", font=small)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def specimen_jpeg(*, label: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 600), "#F4F1EA")
    draw = ImageDraw.Draw(img)
    draw.rectangle((30, 30, 870, 570), outline="#888888", width=3)
    draw.text((60, 70), label, fill="#333333", font=_font(34))
    for i in range(6):
        draw.line((60, 170 + 50 * i, 840, 170 + 50 * i), fill="#BBBBBB", width=2)
    wm = _font(52)
    draw.text((90, 270), SPECIMEN, fill="#C0392B", font=wm)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def specimen_pdf(*, title: str, lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, h - 80, title)
    c.setFont("Helvetica", 11)
    for i, line in enumerate(lines):
        c.drawString(60, h - 120 - 18 * i, line)
    c.saveState()
    c.setFillColorRGB(0.75, 0.2, 0.15, alpha=0.35)
    c.setFont("Helvetica-Bold", 40)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, SPECIMEN)
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()
