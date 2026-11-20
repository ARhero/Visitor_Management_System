"""PDFs (evacuation list, visit log, report) with fpdf2: pure Python, no system
libraries. Noto Sans + Noto Sans Devanagari are bundled (SIL OFL, see
app/assets/fonts/OFL.txt); HarfBuzz shaping makes Hindi conjuncts render correctly,
and Devanagari falls back automatically inside English text."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.services.visits import IST

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
INK = (28, 33, 33)
MUTED = (110, 118, 118)
LINE = (220, 222, 218)
BRAND = (15, 76, 92)
PAPER = (246, 245, 241)
BOX = "☐"  # table cell value drawn as an empty tick box


def ist(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    return dt.astimezone(IST).strftime(fmt).replace(" 0", " ") if dt else ""


def _rgb(hex_color: str | None) -> tuple[int, int, int]:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return BRAND
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class Doc(FPDF):
    def __init__(
        self, title: str, subtitle: str, org: str, color: str | None = None, landscape: bool = False
    ) -> None:
        super().__init__(orientation="L" if landscape else "P", format="A4")
        self.title_text, self.subtitle, self.org = title, subtitle, org
        self.brand = _rgb(color)
        self.generated = datetime.now(IST)
        for style, suffix in (("", "Regular"), ("B", "Bold")):
            self.add_font("noto", style, str(FONTS / f"NotoSans-{suffix}.ttf"))
            self.add_font("deva", style, str(FONTS / f"NotoSansDevanagari-{suffix}.ttf"))
        self.set_fallback_fonts(["deva"])
        self.set_text_shaping(True)
        self.set_auto_page_break(True, margin=16)
        self.set_margins(14, 14, 14)
        self.set_title(title)
        self.set_author(org)
        self.add_page()

    def header(self) -> None:
        self.set_fill_color(*self.brand)
        self.rect(0, 0, self.w, 3, "F")
        self.set_xy(self.l_margin, 8)
        self.set_font("noto", "B", 15)
        self.set_text_color(*INK)
        self.cell(0, 8, self.title_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("noto", "", 9)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"{self.org} · {self.subtitle}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_font("noto", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            5,
            f"Generated {ist(self.generated)} IST · Confidential: contains personal data",
            align="L",
        )
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    # ---------- building blocks ----------

    def heading(self, text: str) -> None:
        if self.get_y() > self.h - 40:
            self.add_page()
        self.ln(2)
        self.set_font("noto", "B", 11)
        self.set_text_color(*INK)
        self.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def note(self, text: str) -> None:
        self.set_font("noto", "", 8.5)
        self.set_text_color(*MUTED)
        self.multi_cell(0, 4.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def stats(self, items: Sequence[tuple[str, str]]) -> None:
        """A row of big numbers with labels."""
        w = (self.w - self.l_margin - self.r_margin) / max(len(items), 1)
        y = self.get_y()
        for i, (label, value) in enumerate(items):
            x = self.l_margin + i * w
            self.set_fill_color(*PAPER)
            self.rect(x + 1, y, w - 2, 17, "F")
            self.set_xy(x + 4, y + 2)
            self.set_font("noto", "B", 14)
            self.set_text_color(*INK)
            self.cell(w - 8, 7, value)
            self.set_xy(x + 4, y + 9.5)
            self.set_font("noto", "", 7.5)
            self.set_text_color(*MUTED)
            self.cell(w - 8, 5, label)
        self.set_xy(self.l_margin, y + 21)

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        widths: Sequence[float],
        font_size: float = 8,
    ) -> None:
        """Simple table that repeats its header on every page. Widths are relative."""
        total = self.w - self.l_margin - self.r_margin
        ws = [total * x / sum(widths) for x in widths]
        line_h = font_size * 0.5

        def head() -> None:
            self.set_font("noto", "B", font_size)
            self.set_fill_color(*PAPER)
            self.set_text_color(*INK)
            for h, w in zip(headers, ws, strict=True):
                self.cell(w, line_h + 3, h, fill=True)
            self.ln(line_h + 3)

        head()
        self.set_font("noto", "", font_size)
        for row in rows:
            cells = ["" if v is None else str(v) for v in row]
            # Height: the tallest cell once wrapped.
            lines = max(
                (
                    len(
                        self.multi_cell(w - 1.5, line_h, c, dry_run=True, output="LINES", align="L")
                        or [""]
                    )
                    for c, w in zip(cells, ws, strict=True)
                    if c and c != BOX
                ),
                default=1,
            )
            hgt = lines * line_h + 2.5
            if self.get_y() + hgt > self.h - self.b_margin:
                self.add_page()
                head()
                self.set_font("noto", "", font_size)
            y = self.get_y()
            x = self.l_margin
            self.set_text_color(*INK)
            for c, w in zip(cells, ws, strict=True):
                if c == BOX:  # an empty tick box to mark by hand
                    self.set_draw_color(*INK)
                    self.rect(x + 1.2, y + 1.6, 3.4, 3.4)
                else:
                    self.set_xy(x + 0.75, y + 1.2)
                    self.multi_cell(w - 1.5, line_h, c, align="L")
                x += w
            self.set_draw_color(*LINE)
            self.line(self.l_margin, y + hgt, self.l_margin + total, y + hgt)
            self.set_xy(self.l_margin, y + hgt)

    def bars(
        self, data: Sequence[tuple[str, float]], height: float = 46, value_fmt: str = "{:g}"
    ) -> None:
        """Vertical bar chart; labels thinned out when there are many bars."""
        if not data:
            return
        if self.get_y() + height + 10 > self.h - self.b_margin:
            self.add_page()
        total_w = self.w - self.l_margin - self.r_margin
        top = max(v for _, v in data) or 1
        n = len(data)
        slot = total_w / n
        bw = max(min(slot * 0.7, 14), 0.8)
        y0 = self.get_y() + height
        every = max(1, round(n / 16))
        self.set_draw_color(*LINE)
        self.line(self.l_margin, y0, self.l_margin + total_w, y0)
        for i, (label, v) in enumerate(data):
            h = (v / top) * (height - 6)
            x = self.l_margin + i * slot + (slot - bw) / 2
            self.set_fill_color(*self.brand)
            if h > 0:
                self.rect(x, y0 - h, bw, h, "F")
            if v and n <= 31:
                self.set_font("noto", "", 6)
                self.set_text_color(*MUTED)
                self.set_xy(x - 3, y0 - h - 4)
                self.cell(bw + 6, 3.5, value_fmt.format(v), align="C")
            if i % every == 0:
                self.set_font("noto", "", 6.5)
                self.set_text_color(*MUTED)
                self.set_xy(self.l_margin + i * slot - 4, y0 + 1)
                self.cell(slot + 8, 4, label, align="C")
        self.set_xy(self.l_margin, y0 + 8)

    def hbars(self, data: Sequence[tuple[str, float]], value_fmt: str = "{:g}") -> None:
        """Horizontal bars with labels on the left, for rankings."""
        if not data:
            return
        total_w = self.w - self.l_margin - self.r_margin
        label_w = total_w * 0.32
        top = max(v for _, v in data) or 1
        for label, v in data:
            if self.get_y() + 7 > self.h - self.b_margin:
                self.add_page()
            y = self.get_y()
            self.set_font("noto", "", 8)
            self.set_text_color(*INK)
            self.set_xy(self.l_margin, y)
            self.cell(label_w - 2, 5.5, label[:48])
            w = (total_w - label_w - 14) * v / top
            self.set_fill_color(*self.brand)
            if w > 0:
                self.rect(self.l_margin + label_w, y + 1, w, 3.5, "F")
            self.set_xy(self.l_margin + label_w + w + 1.5, y)
            self.set_text_color(*MUTED)
            self.cell(12, 5.5, value_fmt.format(v))
            self.set_xy(self.l_margin, y + 6.5)

    def render(self) -> bytes:
        self.alias_nb_pages()
        return bytes(self.output())


def duration(seconds: int | None) -> str:
    if seconds is None:
        return "–"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s:02d}s" if m < 10 else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"
