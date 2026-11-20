"""Printable A4 QR posters, one page per gate, in the org's colours with its logo.

The QR is drawn as vector squares (not an image), so it stays sharp at any print size.
Text is in English and Hindi; visitors choose their language on the check-in page.
"""

import io
from dataclasses import dataclass

import segno
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image

from app.services.pdf import FONTS, INK, MUTED, PAPER, _rgb

STEPS = (
    ("Scan the code with your phone camera", "फ़ोन के कैमरे से कोड स्कैन करें"),
    ("Verify your number on WhatsApp", "WhatsApp पर अपना नंबर सत्यापित करें"),
    ("Show your pass once your host approves", "स्वीकृति के बाद गेट पर पास दिखाएँ"),
)


@dataclass
class PosterGate:
    site: str
    gate: str
    url: str


class Poster(FPDF):
    def __init__(self, org: str, primary: str | None, accent: str | None, logo: bytes | None):
        super().__init__(orientation="P", format="A4")
        for style, suffix in (("", "Regular"), ("B", "Bold")):
            self.add_font("noto", style, str(FONTS / f"NotoSans-{suffix}.ttf"))
            self.add_font("deva", style, str(FONTS / f"NotoSansDevanagari-{suffix}.ttf"))
        self.set_fallback_fonts(["deva"])
        self.set_text_shaping(True)
        self.set_auto_page_break(False)
        self.set_margins(16, 16, 16)
        self.org = org
        self.primary = _rgb(primary)
        self.accent = _rgb(accent) if accent else self.primary
        self.logo = _logo_png(logo) if logo else None
        self.set_title(f"{org}: visitor check-in posters")
        self.set_author(org)

    def centered(self, text: str, size: float, style: str = "", color=INK, h: float = 0) -> None:  # noqa: ANN001
        self.set_font("noto", style, size)
        self.set_text_color(*color)
        self.set_x(self.l_margin)
        self.multi_cell(0, h or size * 0.48, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def page_for(self, g: PosterGate, retention_days: int, privacy_url: str) -> None:
        self.add_page()
        w = self.w
        # Brand band
        self.set_fill_color(*self.primary)
        self.rect(0, 0, w, 40, "F")
        x = self.l_margin
        if self.logo:
            self.set_fill_color(255, 255, 255)
            self.rect(x, 8, 24, 24, "F", round_corners=True, corner_radius=3)
            self.image(self.logo, x + 2, 10, 20, 20, keep_aspect_ratio=True)
            x += 30
        self.set_text_color(255, 255, 255)
        self.set_xy(x, 11)
        self.set_font("noto", "B", 19)
        self.cell(w - x - self.r_margin, 9, self.org)
        self.set_xy(x, 21)
        self.set_font("noto", "", 11)
        self.cell(w - x - self.r_margin, 6, g.site)

        # Headline
        self.set_y(52)
        self.centered("Visitor check-in", 34, "B", h=14)
        self.centered("आगंतुक चेक-इन", 20, "B", MUTED, h=11)
        self.ln(2)
        self.centered("Scan with your phone camera. No app needed.", 13, h=7)
        self.centered("अपने फ़ोन के कैमरे से स्कैन करें। कोई ऐप ज़रूरी नहीं।", 11, color=MUTED, h=6)

        # QR, in an accent frame
        size = 104.0
        qx, qy = (w - size) / 2, self.get_y() + 7
        self.set_draw_color(*self.accent)
        self.set_line_width(1.6)
        self.rect(qx - 7, qy - 7, size + 14, size + 14, "D", round_corners=True, corner_radius=6)
        self._qr(g.url, qx, qy, size)

        # Which gate this is
        label = f"{g.site} · {g.gate}"
        self.set_font("noto", "B", 13)
        lw = min(self.get_string_width(label) + 14, w - 2 * self.l_margin)
        ly = qy + size + 12
        self.set_fill_color(*PAPER)
        self.rect((w - lw) / 2, ly, lw, 10, "F", round_corners=True, corner_radius=5)
        self.set_xy((w - lw) / 2, ly)
        self.set_text_color(*INK)
        self.cell(lw, 10, label, align="C")

        # Three steps
        top = ly + 19
        col = (w - self.l_margin - self.r_margin) / 3
        for i, (en, hi) in enumerate(STEPS):
            cx = self.l_margin + i * col
            self.set_fill_color(*self.primary)
            self.ellipse(cx + col / 2 - 5, top, 10, 10, "F")
            self.set_xy(cx + col / 2 - 5, top)
            self.set_font("noto", "B", 12)
            self.set_text_color(255, 255, 255)
            self.cell(10, 10, str(i + 1), align="C")
            self.set_xy(cx + 3, top + 13)
            self.set_font("noto", "B", 9.5)
            self.set_text_color(*INK)
            self.multi_cell(col - 6, 4.6, en, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_x(cx + 3)
            self.set_font("noto", "", 9)
            self.set_text_color(*MUTED)
            self.multi_cell(col - 6, 4.6, hi, align="C")

        # Footer: fallback link and privacy line
        self.set_y(self.h - 24)
        self.set_draw_color(225, 225, 220)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), w - self.r_margin, self.get_y())
        self.ln(3)
        self.centered(f"Can't scan? Open {g.url}", 8, color=MUTED, h=4.2)
        self.centered(
            f"Your details are used only to manage your visit and are deleted after "
            f"{retention_days} days (DPDP Act, 2023). Your data: {privacy_url}",
            7.5,
            color=MUTED,
            h=4,
        )

    def _qr(self, data: str, x: float, y: float, size: float) -> None:
        qr = segno.make(data, error="m", micro=False)
        rows = [list(r) for r in qr.matrix_iter(scale=1, border=0)]
        n = len(rows)
        cell = size / n
        self.set_fill_color(*INK)
        for r, row in enumerate(rows):
            c = 0
            while c < n:
                if row[c]:
                    start = c
                    while c < n and row[c]:
                        c += 1
                    # A hair of overlap avoids white seams between squares in some viewers.
                    self.rect(
                        x + start * cell, y + r * cell, (c - start) * cell + 0.05, cell + 0.05, "F"
                    )
                else:
                    c += 1


def _logo_png(raw: bytes) -> io.BytesIO | None:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:  # noqa: BLE001
        return None
    out = io.BytesIO()
    img.convert("RGBA").save(out, format="PNG")
    out.seek(0)
    return out


def build(
    org: str,
    branding: dict,
    logo: bytes | None,
    gates: list[PosterGate],
    retention_days: int,
    privacy_url: str,
) -> bytes:
    doc = Poster(org, branding.get("primary_color"), branding.get("accent_color"), logo)
    for g in gates:
        doc.page_for(g, retention_days, privacy_url)
    return bytes(doc.output())
