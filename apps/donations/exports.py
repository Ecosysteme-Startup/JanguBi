"""Reçu de don (PDF simple, jamais fiscal) et export comptable (CSV, XLSX).

L'XLSX est écrit à la main (un classeur, une feuille, chaînes en ligne) : pas de dépendance
supplémentaire dans l'image pour un tableau plat.
"""

import csv
import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

from django.utils import timezone

from apps.donations.models import Donation

EXPORT_COLUMNS = [
    ("date", "Date"),
    ("reference", "Référence"),
    ("fonds", "Fonds"),
    ("type", "Type"),
    ("destination", "Destination"),
    ("canal", "Canal"),
    ("moyen", "Moyen"),
    ("statut", "Statut"),
    ("don", "Don (FCFA)"),
    ("frais", "Frais (FCFA)"),
    ("paye", "Payé (FCFA)"),
    ("affecte", "Affecté (FCFA)"),
    ("donateur", "Donateur"),
    ("reversement", "Reversement"),
]


def fcfa(value: int, *, thin: str = "\u202f") -> str:
    """« 5 000 FCFA » avec espaces insécables (typographie française, ENF-09). Le PDF passe
    ``thin="\\u00a0"`` : les polices standard de reportlab n'ont pas l'espace fine."""
    return f"{value:,}".replace(",", thin) + "\u00a0FCFA"


def receipt_pdf(donation: Donation) -> bytes:
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5)
    width, height = A5
    y = height - 20 * mm
    pdf.setTitle(f"Reçu de don {donation.reference}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(15 * mm, y, "Reçu de don")
    y -= 8 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawString(15 * mm, y, "Jàngu Bi — reçu simple, ce n'est pas un reçu fiscal.")
    y -= 14 * mm
    confirmed = timezone.localtime(donation.confirmed_at) if donation.confirmed_at else None
    lines = [
        ("Référence", donation.reference),
        ("Date", confirmed.strftime("%d/%m/%Y") if confirmed else "—"),
        ("Paroisse", donation.fund.node.name),
        ("Fonds", donation.fund.title),
        ("Montant du don", fcfa(donation.amount, thin="\u00a0")),
    ]
    if donation.fees_covered:
        lines.append(("Frais de paiement couverts", fcfa(donation.fee_amount, thin="\u00a0")))
    for label, value in lines:
        pdf.setFont("Helvetica", 10)
        pdf.drawString(15 * mm, y, f"{label} :")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(60 * mm, y, value)
        y -= 7 * mm
    y -= 6 * mm
    pdf.setFont("Helvetica", 8)
    pdf.drawString(15 * mm, y, "Le paiement a été traité par un agrégateur agréé ; Jàngu Bi ne détient pas les fonds.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def export_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([row[key] for key, _ in EXPORT_COLUMNS])
    return ("﻿" + buffer.getvalue()).encode()  # BOM : ouverture correcte dans Excel


def _cell(ref: str, value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def export_xlsx(rows: list[dict[str, Any]]) -> bytes:
    table = [[label for _, label in EXPORT_COLUMNS]] + [[row[key] for key, _ in EXPORT_COLUMNS] for row in rows]
    sheet_rows = "".join(
        f'<row r="{r + 1}">' + "".join(_cell(f"{_col(c)}{r + 1}", v) for c, v in enumerate(values)) + "</row>"
        for r, values in enumerate(table)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="xl/workbook.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Dons" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{sheet_rows}</sheetData></worksheet>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
