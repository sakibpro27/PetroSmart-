"""
Build the PDF documents from the Markdown files, so the PDF never drifts
from the editable text.

Run from the project folder (with the virtual environment active):

    python documentation/tools/build_report.py

Writes
    documentation/academic/PetroSmart-Project-Report.pdf   (chapters + appendices)
    documentation/user-manual/PetroSmart-User-Manual.pdf

Markdown understood: headings (# to ####), paragraphs, bullet and numbered
lists, tables, fenced code blocks, **bold**, *italic*, `code` and [links](url).
Markers on a line of their own:
    {{titlepage}}  {{pagebreak}}  {{toc}}
    {{diagram:name}}                      a figure from diagrams.py
    {{screenshot:file.png|Caption}}       an image from documentation/screenshots/,
                                          or a labelled empty box until it exists
Fonts: Arial and Consolas from Windows (they include the ₹ sign).
"""

import math
import os
import re
import sys
from pathlib import Path

from reportlab.graphics.shapes import Circle, Drawing, Ellipse, Group, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                Preformatted, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

TOOLS = Path(__file__).resolve().parent
DOCS = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from diagrams import DIAGRAMS  # noqa: E402

REPORT_FILES = [
    "00-front-matter.md", "01-introduction.md", "02-system-analysis.md", "03-system-design.md",
    "04-implementation.md", "05-testing.md", "06-installation-and-user-guide.md", "07-conclusion.md",
    "08-references.md", "appendix-a-data-dictionary.md", "appendix-b-test-results.md",
]

# --- Look -------------------------------------------------------------------------------

GREEN = colors.HexColor("#24543A")
INK = colors.HexColor("#1F2A24")
MUTED = colors.HexColor("#5B665F")
RULE = colors.HexColor("#C3CEC6")
IVORY = colors.HexColor("#F6F2E7")
PALE = colors.HexColor("#E8F0EA")

PAGE_W, PAGE_H = A4
LEFT, RIGHT, TOP, BOTTOM = 85, 57, 70, 64  # 3 cm binding margin on the left
WIDTH = PAGE_W - LEFT - RIGHT


def register_fonts():
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    faces = {"Body": "arial.ttf", "Body-Bold": "arialbd.ttf", "Body-Italic": "ariali.ttf",
             "Body-BoldItalic": "arialbi.ttf", "Mono": "consola.ttf"}
    for name, file in faces.items():
        if not (folder / file).exists():
            raise SystemExit(f"Font {folder / file} not found. This script uses the Windows fonts Arial and Consolas.")
        pdfmetrics.registerFont(TTFont(name, str(folder / file)))
    registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")
    registerFontFamily("Mono", normal="Mono", bold="Mono", italic="Mono", boldItalic="Mono")


def make_styles():
    s = {}
    s["body"] = ParagraphStyle("body", fontName="Body", fontSize=11, leading=15.5, textColor=INK,
                               alignment=TA_JUSTIFY, spaceAfter=7)
    s["center"] = ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER, fontSize=12.5, leading=19,
                                 spaceAfter=10)
    s["title"] = ParagraphStyle("title", fontName="Body-Bold", fontSize=23, leading=30, textColor=GREEN,
                                alignment=TA_CENTER, spaceAfter=40)
    s["h1"] = ParagraphStyle("h1", fontName="Body-Bold", fontSize=19, leading=24, textColor=GREEN, spaceAfter=16)
    s["h2"] = ParagraphStyle("h2", fontName="Body-Bold", fontSize=13.5, leading=18, textColor=GREEN,
                             spaceBefore=14, spaceAfter=6, keepWithNext=1)
    s["h2c"] = ParagraphStyle("h2c", parent=s["h2"], alignment=TA_CENTER, fontSize=16, spaceAfter=14)
    s["h3"] = ParagraphStyle("h3", fontName="Body-Bold", fontSize=11.5, leading=15, textColor=INK,
                             spaceBefore=10, spaceAfter=4, keepWithNext=1)
    s["h4"] = ParagraphStyle("h4", parent=s["h3"], fontName="Body-BoldItalic", fontSize=11)
    s["note_left"] = ParagraphStyle("note_left", parent=s["body"], alignment=0)
    s["item"] = ParagraphStyle("item", parent=s["body"], alignment=0, spaceAfter=3)
    s["code"] = ParagraphStyle("code", fontName="Mono", fontSize=8.6, leading=11.2, textColor=INK)
    s["cell"] = ParagraphStyle("cell", fontName="Body", fontSize=8.6, leading=10.8, textColor=INK)
    s["head"] = ParagraphStyle("head", parent=s["cell"], fontName="Body-Bold", textColor=colors.white)
    s["caption"] = ParagraphStyle("caption", fontName="Body-Italic", fontSize=9.5, leading=12, textColor=MUTED,
                                  alignment=TA_CENTER, spaceBefore=4, spaceAfter=4)
    s["note"] = ParagraphStyle("note", fontName="Body", fontSize=9, leading=11.5, textColor=MUTED,
                               alignment=TA_CENTER, spaceAfter=12)
    return s


# --- Markdown -----------------------------------------------------------------------------

LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
MARKER_RE = re.compile(r"^\{\{(\w+)(?::(.*))?\}\}$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")


def inline(text, mono_size=10):
    """Markdown inline formatting to ReportLab paragraph markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes = []

    def keep(match):
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<i>\1</i>", text)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: f'<font face="Mono" size="{mono_size}">{codes[int(m.group(1))]}</font>', text)


def plain(text):
    return re.sub(r"\*\*|`|\*", "", re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text))


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def starts_block(line):
    stripped = line.strip()
    return (stripped.startswith(("|", "```")) or HEADING_RE.match(stripped) or MARKER_RE.match(stripped)
            or (LIST_RE.match(line) and not line.startswith(" ")))


def parse(text):
    """Split Markdown into blocks: (kind, ...)."""
    lines, blocks, i = text.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
        elif stripped.startswith("```"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(body)))
            i += 1
        elif MARKER_RE.match(stripped):
            m = MARKER_RE.match(stripped)
            blocks.append(("marker", m.group(1), m.group(2) or ""))
            i += 1
        elif HEADING_RE.match(stripped):
            m = HEADING_RE.match(stripped)
            blocks.append(("heading", len(m.group(1)), m.group(2).strip()))
            i += 1
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_row(lines[i])
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
        elif LIST_RE.match(line):
            items = []
            while i < len(lines) and lines[i].strip():
                m = LIST_RE.match(lines[i])
                if m:
                    items.append([len(m.group(1)) // 2, m.group(2), m.group(3)])
                elif items and not starts_block(lines[i]):
                    items[-1][2] += " " + lines[i].strip()
                else:
                    break
                i += 1
            blocks.append(("list", items))
        else:
            body = []
            while i < len(lines) and lines[i].strip() and (not body or not starts_block(lines[i])):
                body.append(lines[i].strip())
                i += 1
            blocks.append(("para", " ".join(body)))
    return blocks


# --- Tables --------------------------------------------------------------------------------

def column_widths(rows, available, size):
    columns = max(len(r) for r in rows)
    natural, minimum = [0.0] * columns, [0.0] * columns
    for r, row in enumerate(rows):
        font = "Body-Bold" if r == 0 else "Body"
        for c, cell in enumerate(row):
            # `code` is drawn in the monospaced font, which is wider than the body font.
            parts = [(plain(part), "Mono" if n % 2 else font) for n, part in enumerate(cell.split("`"))]
            natural[c] = max(natural[c], sum(stringWidth(t, f, size) for t, f in parts) + 10)
            longest = max((stringWidth(w, f, size) for t, f in parts for w in t.split()), default=0)
            minimum[c] = max(minimum[c], min(longest + 10, available * 0.4))
    if sum(natural) <= available:
        return [w * available / sum(natural) for w in natural]
    spare = available - sum(minimum)
    if spare <= 0:
        return [w * available / sum(minimum) for w in minimum]
    stretch = [max(n - m, 0) for n, m in zip(natural, minimum)]
    return [m + spare * s / (sum(stretch) or 1) for m, s in zip(minimum, stretch)]


def make_table(rows, styles):
    columns = max(len(r) for r in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    data = [[Paragraph(inline(cell, 8), styles["head" if r == 0 else "cell"]) for cell in row]
            for r, row in enumerate(rows)]
    table = Table(data, colWidths=column_widths(rows, WIDTH, 8.6), repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5), ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
    ]
    commands += [("BACKGROUND", (0, r), (-1, r), IVORY) for r in range(2, len(rows), 2)]
    table.setStyle(TableStyle(commands))
    return table


# --- Diagrams ------------------------------------------------------------------------------

NODE_FONT, LABEL_FONT = 7.4, 6.6


def text_lines(group, lines, cx, top, size, font="Body", color=INK, leading=None):
    leading = leading or size * 1.22
    for n, line in enumerate(lines):
        group.add(String(cx, top - size - n * leading, line, fontName=font, fontSize=size, fillColor=color,
                         textAnchor="middle"))


def centred_text(group, label, cx, cy, size=NODE_FONT, font="Body"):
    lines = label.split("\n")
    leading = size * 1.22
    top = cy + len(lines) * leading / 2 + size * 0.1
    text_lines(group, lines, cx, top, size, font, leading=leading)


def draw_node(g, node):
    x, y, w, h = node.x, node.y, node.w, node.h
    cx, cy = x + w / 2, y + h / 2
    line = dict(strokeColor=INK, strokeWidth=0.8)
    if node.shape == "box":
        g.add(Rect(x, y, w, h, fillColor=PALE, **line))
        centred_text(g, node.label, cx, cy)
    elif node.shape == "round":
        g.add(Rect(x, y, w, h, rx=8, ry=8, fillColor=PALE, **line))
        centred_text(g, node.label, cx, cy)
    elif node.shape == "ellipse":
        g.add(Ellipse(cx, cy, w / 2, h / 2, fillColor=PALE, **line))
        centred_text(g, node.label, cx, cy)
    elif node.shape == "circle":
        if node.label:
            g.add(Ellipse(cx, cy, w / 2, h / 2, fillColor=PALE, **line))
            centred_text(g, node.label, cx, cy)
        else:
            g.add(Circle(cx, cy, min(w, h) / 2, fillColor=INK, strokeColor=INK))
    elif node.shape == "terminal":
        g.add(Circle(cx, cy, min(w, h) / 2, fillColor=colors.white, **line))
        g.add(Circle(cx, cy, min(w, h) / 2 - 3.5, fillColor=INK, strokeColor=INK))
    elif node.shape == "diamond":
        g.add(Polygon([cx, y + h, x + w, cy, cx, y, x, cy], fillColor=IVORY, **line))
        centred_text(g, node.label, cx, cy, size=NODE_FONT - 0.6)
    elif node.shape == "store":
        g.add(Rect(x, y, w, h, fillColor=IVORY, strokeColor=None))
        g.add(Line(x, y + h, x + w, y + h, **line))
        g.add(Line(x, y, x + w, y, **line))
        g.add(Line(x, y, x, y + h, **line))
        centred_text(g, node.label, cx, cy)
    elif node.shape == "actor":
        lines = node.label.split("\n")
        label_h = len(lines) * NODE_FONT * 1.22
        fig_top, fig_bottom = y + h, y + label_h + 3
        head = (fig_top - fig_bottom) * 0.18
        neck = fig_top - 2 * head
        hip = fig_bottom + (fig_top - fig_bottom) * 0.35
        g.add(Circle(cx, fig_top - head, head, fillColor=colors.white, **line))
        g.add(Line(cx, neck, cx, hip, **line))
        g.add(Line(cx - head * 1.6, neck - head * 0.8, cx + head * 1.6, neck - head * 0.8, **line))
        g.add(Line(cx, hip, cx - head * 1.3, fig_bottom, **line))
        g.add(Line(cx, hip, cx + head * 1.3, fig_bottom, **line))
        text_lines(g, lines, cx, y + label_h, NODE_FONT, "Body-Bold")
    elif node.shape == "class":
        parts = node.label.split("\n")
        leading, top = NODE_FONT * 1.2, y + h - 3
        titles = parts.index("—") if "—" in parts else len(parts)
        g.add(Rect(x, y, w, h, fillColor=colors.white, **line))
        g.add(Rect(x, y + h - 3 - titles * leading - 2.5, w, titles * leading + 5.5, fillColor=PALE, **line))
        for n, part in enumerate(parts):
            if part == "—":
                if n > titles:
                    g.add(Line(x, top - leading * 0.3, x + w, top - leading * 0.3, **line))
                top -= leading * 0.6
                continue
            title = n < titles
            g.add(String(cx if title else x + 5, top - NODE_FONT, part, fontName="Body-Bold" if title else "Body",
                         fontSize=NODE_FONT, fillColor=INK, textAnchor="middle" if title else "start"))
            top -= leading
    elif node.shape == "boundary":
        g.add(Rect(x, y, w, h, fillColor=None, strokeColor=MUTED, strokeWidth=0.9))
        g.add(String(cx, y + h - 13, node.label, fontName="Body-Bold", fontSize=NODE_FONT + 1, fillColor=MUTED,
                     textAnchor="middle"))


def boundary(node, toward):
    """Point where the line from the node's centre toward `toward` leaves its outline."""
    cx, cy = node.x + node.w / 2, node.y + node.h / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    a, b = node.w / 2, node.h / 2
    if node.shape in ("ellipse", "circle", "terminal"):
        if node.shape != "ellipse" and not (node.shape == "circle" and node.label):
            a = b = min(a, b)
        t = 1 / math.sqrt((dx / a) ** 2 + (dy / b) ** 2)
    elif node.shape == "diamond":
        t = 1 / (abs(dx) / a + abs(dy) / b)
    else:
        t = min(a / abs(dx) if dx else math.inf, b / abs(dy) if dy else math.inf)
    return cx + dx * t, cy + dy * t


def arrow_head(g, x1, y1, x2, y2, size=5.5, hollow=False):
    angle = math.atan2(y2 - y1, x2 - x1)
    spread = 0.5 if hollow else 0.4
    size = 9 if hollow else size
    left = (x2 - size * math.cos(angle - spread), y2 - size * math.sin(angle - spread))
    right = (x2 - size * math.cos(angle + spread), y2 - size * math.sin(angle + spread))
    g.add(Polygon([x2, y2, *left, *right], fillColor=colors.white if hollow else INK, strokeColor=INK,
                  strokeWidth=0.7 if hollow else 0.5))


def edge_label(g, text, x, y):
    lines = text.split("\n")
    leading = LABEL_FONT * 1.2
    width = max(stringWidth(t, "Body", LABEL_FONT) for t in lines) + 4
    height = len(lines) * leading + 1
    g.add(Rect(x - width / 2, y - height / 2, width, height, fillColor=colors.white, strokeColor=None))
    text_lines(g, lines, x, y + height / 2 - 0.3, LABEL_FONT, color=MUTED, leading=leading)


def centre(node):
    return node.x + node.w / 2, node.y + node.h / 2


def draw_graph(d):
    g = Group()
    nodes = {n.id: n for n in d.nodes}
    pairs = {(e.src, e.dst) for e in d.edges}
    labels = []
    for node in d.nodes:
        if node.shape == "boundary":
            draw_node(g, node)
    for edge in d.edges:
        src, dst = nodes[edge.src], nodes[edge.dst]
        points = [boundary(src, edge.via[0] if edge.via else centre(dst)), *edge.via,
                  boundary(dst, edge.via[-1] if edge.via else centre(src))]
        side = 0
        if (edge.dst, edge.src) in pairs and not edge.via:
            # Two flows in opposite directions: draw them side by side, labels on their own side.
            first, second = sorted((src, dst), key=lambda n: n.id)
            (ax, ay), (bx, by) = centre(first), centre(second)
            length = math.hypot(bx - ax, by - ay) or 1
            side = 1 if src is first else -1
            px, py = -(by - ay) / length, (bx - ax) / length
            points = [(x + px * 4.5 * side, y + py * 4.5 * side) for x, y in points]
        flat = [c for p in points for c in p]
        g.add(PolyLine(flat, strokeColor=INK, strokeWidth=0.7, strokeDashArray=[3, 2] if edge.dashed else None))
        if edge.arrow or edge.hollow:
            arrow_head(g, *points[-2], *points[-1], hollow=edge.hollow)
        if edge.label:
            segments = list(zip(points, points[1:]))
            (ax, ay), (bx, by) = max(segments, key=lambda s: math.dist(*s))
            lx, ly = ax + (bx - ax) * edge.label_at, ay + (by - ay) * edge.label_at
            if side:
                lines = edge.label.split("\n")
                height = len(lines) * LABEL_FONT * 1.2
                width = max(stringWidth(t, "Body", LABEL_FONT) for t in lines)
                lx += px * side * (width / 2 + 3) * abs(px) + px * side * 3
                ly += py * side * (height / 2 + 3)
            labels.append((edge.label, lx, ly))
    for node in d.nodes:
        if node.shape != "boundary":
            draw_node(g, node)
    for label in labels:  # on top of everything so they stay readable
        edge_label(g, *label)
    return g


def draw_sequence(d):
    g = Group()
    count = len(d.participants)
    step = d.width / count
    xs = {p: step * (n + 0.5) for n, p in enumerate(d.participants)}
    box_h, top = 24, d.height
    for p, x in xs.items():
        w = min(step - 6, max(stringWidth(p, "Body-Bold", NODE_FONT) + 10, 50))
        g.add(Rect(x - w / 2, top - box_h, w, box_h, fillColor=PALE, strokeColor=INK, strokeWidth=0.8))
        g.add(String(x, top - box_h / 2 - 2.6, p, fontName="Body-Bold", fontSize=NODE_FONT, fillColor=INK,
                     textAnchor="middle"))
        g.add(Line(x, top - box_h, x, 4, strokeColor=MUTED, strokeWidth=0.6, strokeDashArray=[2, 2]))
    gap = (d.height - box_h - 20) / len(d.messages)
    for n, (src, dst, label, dashed) in enumerate(d.messages):
        y = top - box_h - 18 - n * gap
        x1, x2 = xs[src], xs[dst]
        style = dict(strokeColor=INK, strokeWidth=0.8, strokeDashArray=[3, 2] if dashed else None)
        if src == dst:
            g.add(PolyLine([x1, y + 4, x1 + 26, y + 4, x1 + 26, y - 8, x1 + 2, y - 8], **style))
            arrow_head(g, x1 + 26, y - 8, x1 + 1, y - 8)
            g.add(String(x1 + 30, y - 4, label, fontName="Body", fontSize=LABEL_FONT, fillColor=INK))
            continue
        g.add(Line(x1, y, x2, y, **style))
        arrow_head(g, x1, y, x2, y)
        width = stringWidth(label, "Body", LABEL_FONT) + 4
        mid = (x1 + x2) / 2
        mid = min(max(mid, width / 2), d.width - width / 2)
        g.add(Rect(mid - width / 2, y + 2, width, LABEL_FONT + 2, fillColor=colors.white, strokeColor=None))
        g.add(String(mid, y + 3.6, label, fontName="Body", fontSize=LABEL_FONT, fillColor=INK, textAnchor="middle"))
    return g


def extent(d):
    """Bounding box of everything drawn, so the figure can be fitted to the page."""
    if d.kind == "sequence":
        return 0, 0, d.width, d.height
    xs = [v for n in d.nodes for v in (n.x, n.x + n.w)] + [p[0] for e in d.edges for p in e.via]
    ys = [v for n in d.nodes for v in (n.y, n.y + n.h)] + [p[1] for e in d.edges for p in e.via]
    return min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3


def diagram_flowable(d, max_height=PAGE_H - TOP - BOTTOM - 120):
    x0, y0, x1, y1 = extent(d)
    scale = min(WIDTH / (x1 - x0), max_height / (y1 - y0), 1.15)
    drawing = Drawing((x1 - x0) * scale, (y1 - y0) * scale)
    group = draw_sequence(d) if d.kind == "sequence" else draw_graph(d)
    group.transform = (scale, 0, 0, scale, -x0 * scale, -y0 * scale)
    drawing.add(group)
    drawing.hAlign = "CENTER"
    return drawing


# --- Document ------------------------------------------------------------------------------

class FigureList(TableOfContents):
    def notify(self, kind, stuff):
        if kind == "FigureEntry":
            self.addEntry(*stuff)


class ReportDoc(BaseDocTemplate):
    def __init__(self, path, title, running_title):
        super().__init__(str(path), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP,
                         bottomMargin=BOTTOM, title=title, author="[STUDENT NAME]", subject=title)
        self.running_title = running_title
        self.chapter = ""
        frame = Frame(LEFT, BOTTOM, WIDTH, PAGE_H - TOP - BOTTOM, id="body", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("page", [frame], onPageEnd=self.decorate)])

    def beforeDocument(self):
        self.chapter = ""

    def decorate(self, canvas, doc):
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.setFont("Body", 8.5)
        canvas.setFillColor(MUTED)
        canvas.line(LEFT, PAGE_H - TOP + 22, PAGE_W - RIGHT, PAGE_H - TOP + 22)
        canvas.drawString(LEFT, PAGE_H - TOP + 27, self.running_title)
        if self.chapter:
            canvas.drawRightString(PAGE_W - RIGHT, PAGE_H - TOP + 27, self.chapter)
        canvas.line(LEFT, BOTTOM - 22, PAGE_W - RIGHT, BOTTOM - 22)
        canvas.drawCentredString(PAGE_W / 2, BOTTOM - 36, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        level = getattr(flowable, "toc_level", None)
        if level is not None:
            text = flowable.getPlainText()
            key = flowable.toc_key
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=min(level, 2), closed=level >= 1)
            if level == 0 and flowable.in_toc:
                self.chapter = text
            if flowable.in_toc and level <= 1:
                self.notify("TOCEntry", (level, text, self.page, key))
        figure = getattr(flowable, "figure_entry", None)
        if figure:
            self.notify("FigureEntry", (0, figure, self.page))


class Builder:
    def __init__(self, styles):
        self.s = styles
        self.story = []
        self.toc_on = False
        self.title_mode = False
        self.keys = 0
        self.chapter_no = ""
        self.shots = 0
        self.missing_shots = []

    def add(self, flowable):
        self.story.append(flowable)

    def page_break(self):
        if self.story and not isinstance(self.story[-1], PageBreak):
            self.add(PageBreak())

    def heading(self, level, text, style=None):
        if level == 1 and style is None:
            self.page_break()
            match = re.match(r"(Chapter|Appendix)\s+(\w+)", text)
            self.chapter_no = match.group(2) if match else ""
        style = style or self.s["h2c" if level == 2 and not self.toc_on else f"h{level}"]
        para = Paragraph(inline(text), style)
        self.keys += 1
        para.toc_level, para.toc_key, para.in_toc = level - 1, f"h{self.keys}", self.toc_on
        self.add(para)

    def caption(self, text, flowables, note=""):
        caption = Paragraph(inline(text), self.s["caption"])
        caption.figure_entry = text
        parts = [Spacer(1, 6), *flowables, caption]
        if note:
            parts.append(Paragraph(inline(note), self.s["note"]))
        else:
            parts.append(Spacer(1, 10))
        self.add(KeepTogether(parts))

    def marker(self, name, arg):
        if name == "pagebreak":
            self.title_mode = False
            self.page_break()
        elif name == "titlepage":
            self.title_mode = True
        elif name == "toc":
            self.toc_on = True
            self.page_break()
            self.add(Paragraph("Contents", self.s["h1"]))
            toc = TableOfContents(dotsMinLevel=0)
            toc.levelStyles = [
                ParagraphStyle("toc0", fontName="Body-Bold", fontSize=11, leading=15, leftIndent=0,
                               firstLineIndent=0, spaceBefore=5, textColor=INK),
                ParagraphStyle("toc1", fontName="Body", fontSize=10, leading=13.5, leftIndent=18,
                               firstLineIndent=0, textColor=INK),
            ]
            self.add(toc)
            self.add(PageBreak())
            self.add(Paragraph("List of figures", self.s["h1"]))
            figures = FigureList(dotsMinLevel=0)
            figures.levelStyles = [ParagraphStyle("fig0", fontName="Body", fontSize=10, leading=14, textColor=INK)]
            self.add(figures)
        elif name == "diagram":
            d = DIAGRAMS[arg]
            self.caption(f"Figure {d.figure}: {d.title}", [diagram_flowable(d)], d.note)
        elif name == "screenshot":
            file, _, caption = arg.partition("|")
            self.shots += 1
            number = f"{self.chapter_no}.{self.shots}" if self.chapter_no else str(self.shots)
            self.caption(f"Figure {number}: {caption}", [self.screenshot(file.strip())])
        else:
            raise SystemExit(f"Unknown marker {{{{{name}}}}}")

    def screenshot(self, file):
        path = DOCS / "screenshots" / file
        if path.exists():
            width, height = ImageReader(str(path)).getSize()
            scale = min(WIDTH / width, (PAGE_H - TOP - BOTTOM) * 0.6 / height)
            return Image(str(path), width * scale, height * scale)
        self.missing_shots.append(file)
        box = Drawing(WIDTH, 150)
        box.add(Rect(1, 1, WIDTH - 2, 148, fillColor=IVORY, strokeColor=MUTED, strokeWidth=0.8,
                     strokeDashArray=[4, 3]))
        box.add(String(WIDTH / 2, 82, "Screenshot to be added", fontName="Body-Bold", fontSize=11, fillColor=MUTED,
                       textAnchor="middle"))
        box.add(String(WIDTH / 2, 64, f"Save it as documentation/screenshots/{file} and rebuild the report",
                       fontName="Body", fontSize=9, fillColor=MUTED, textAnchor="middle"))
        return box

    def render(self, blocks):
        for n, block in enumerate(blocks):
            kind = block[0]
            if kind == "heading":
                upcoming = blocks[n + 1] if n + 1 < len(blocks) else None
                if block[1] == 1 and upcoming == ("marker", "titlepage", ""):
                    self.add(Spacer(1, 90))
                    self.heading(1, block[2], self.s["title"])
                else:
                    self.heading(block[1], block[2])
            elif kind == "marker":
                self.marker(block[1], block[2])
            elif kind == "para":
                # A note in italics (e.g. "*Generated by ...*") reads better unjustified.
                style = "center" if self.title_mode else "note_left" if block[1].startswith("*") else "body"
                self.add(Paragraph(inline(block[1]), self.s[style]))
            elif kind == "list":
                for level, bullet, text in block[1]:
                    style = ParagraphStyle(f"li{level}", parent=self.s["item"], leftIndent=20 + level * 16,
                                           bulletIndent=5 + level * 16, bulletFontName="Body")
                    self.add(Paragraph(inline(text), style, bulletText="•" if bullet in "-*" else bullet))
                self.add(Spacer(1, 5))
            elif kind == "table":
                self.add(Spacer(1, 3))
                self.add(make_table(block[1], self.s))
                self.add(Spacer(1, 9))
            elif kind == "code":
                code = Preformatted(block[1], self.s["code"], maxLineLength=92, newLineChars="    ")
                box = Table([[code]], colWidths=[WIDTH], hAlign="LEFT")
                box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), IVORY), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                self.add(Spacer(1, 2))
                self.add(box)
                self.add(Spacer(1, 9))


def missing_glyphs(texts):
    fonts = {name: pdfmetrics.getFont(name).face.charToGlyph for name in ("Body", "Mono")}
    chars = set("".join(texts)) - set("\n\r\t")
    return {name: sorted(c for c in chars if ord(c) not in cmap) for name, cmap in fonts.items()}


def build(files, out, title, running_title, styles):
    texts = [f.read_text(encoding="utf-8") for f in files]
    texts += [d.title + d.note + "".join(n.label for n in d.nodes) + "".join(e.label for e in d.edges)
              + "".join(m[2] for m in d.messages) for d in DIAGRAMS.values()]
    builder = Builder(styles)
    builder.toc_on = len(files) == 1  # a single document (the user manual) has no front matter
    for text in texts[:len(files)]:
        builder.render(parse(text))
    doc = ReportDoc(out, title, running_title)
    doc.multiBuild(builder.story)
    print(f"Wrote {out.relative_to(DOCS.parent)} ({doc.page} pages)")
    for font, chars in missing_glyphs(texts).items():
        if chars:
            print(f"  Warning: font {font} has no glyph for: {' '.join(chars)}")
    if builder.missing_shots:
        print(f"  {len(builder.missing_shots)} screenshots still to add in documentation/screenshots/: "
              + ", ".join(builder.missing_shots))


def main():
    register_fonts()
    styles = make_styles()
    academic = DOCS / "academic"
    build([academic / f for f in REPORT_FILES], academic / "PetroSmart-Project-Report.pdf",
          "PetroSmart: A Multi-Tenant Petrol Pump Management System", "PetroSmart: project report", styles)
    build([DOCS / "user-manual" / "README.md"], DOCS / "user-manual" / "PetroSmart-User-Manual.pdf",
          "PetroSmart User Manual", "PetroSmart: user manual", styles)


if __name__ == "__main__":
    main()
