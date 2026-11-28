"""Build the offline W13 PDF cue card; needs Git, pypdf and ReportLab.

Run from a repository checkout: python submissions/week13/tools/build_pdf_demo_card.py
This reads immutable fixture blobs and does not run the application.
"""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "output/pdf/team11-w13-pdf-demo.pdf"
FIXTURE_COMMIT = "16251df8b1167a740d7f29863144a3859a65e4b9"
MANIFEST = "fixtures/search/w13-v1/manifest.json"
NORMAL_NAME = "regression/group-a/doc01.pdf"
ABNORMAL_NAME = "abnormal/no_text_layer.pdf"
MARKER = "Marker01P1"

WIDTH, HEIGHT = A4
LEFT = 42
CONTENT = WIDTH - 2 * LEFT
INK = colors.HexColor("#142738")
MUTED = colors.HexColor("#435B6D")
LIGHT = colors.HexColor("#CCDBE6")
RULE = colors.HexColor("#D9E3EA")
ACCENT = colors.HexColor("#0C6A60")
TINT = colors.HexColor("#EDF6F3")
LIME = colors.HexColor("#D5F18B")


def git_blob(path):
    return subprocess.check_output(["git", "show", f"{FIXTURE_COMMIT}:{path}"], cwd=ROOT)


def read_fixture(record):
    data = git_blob(record["fixture_path"])
    if len(data) != record["byte_size"] or sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"Frozen fixture identity mismatch: {record['fixture_path']}")
    return PdfReader(BytesIO(data), strict=True)


def static_reference():
    files = {row["relative_path"]: row for row in json.loads(git_blob(MANIFEST))["files"]}
    record = files[NORMAL_NAME]
    normal = read_fixture(record)
    pages = [page.extract_text() for page in normal.pages]
    if len(pages) != record["page_count"] or len(pages) != 2:
        raise ValueError("Expected the frozen two-page positive fixture")
    if [index for index, page in enumerate(pages) if MARKER in page] != [0]:
        raise ValueError(f"Expected {MARKER} on physical fixture page 1 only")
    abnormal = files[ABNORMAL_NAME]
    if abnormal["error_code"] != "no_text_layer" or any(
        page.extract_text().strip() for page in read_fixture(abnormal).pages
    ):
        raise ValueError("Expected the frozen no-text-layer fixture")
    return record, pages[0].splitlines()


def text(pdf, x, y, value, size, color=INK, font="Helvetica"):
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    pdf.drawString(x, y, value)


def paragraph(pdf, x, top, content, width):
    style = ParagraphStyle("copy", fontName="Helvetica", fontSize=10.5, leading=13.5, textColor=INK)
    block = Paragraph(content, style)
    _, height = block.wrap(width, HEIGHT)
    block.drawOn(pdf, x, top - height)
    return top - height


def step(pdf, top, number, title, details):
    if number > 1:
        pdf.setStrokeColor(RULE)
        pdf.setLineWidth(0.45)
        pdf.line(LEFT, top + 9, WIDTH - LEFT, top + 9)
    text(pdf, LEFT, top - 3, f"{number:02d}", 11, ACCENT, "Courier-Bold")
    text(pdf, LEFT + 34, top - 3, title, 12.5, INK, "Helvetica-Bold")
    if paragraph(pdf, LEFT + 34, top - 9, details, CONTENT - 34) < top - 40:
        raise ValueError(f"Demo step {number} no longer fits the card")


def main():
    record, excerpt = static_reference()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, invariant=True)
    pdf.setTitle("File Management Assistant | W13 PDF fallback cue card")
    pdf.setAuthor("Team 11 / Role D")
    pdf.setCreator("Team 11 W13 cue card generator")
    pdf.setSubject("Offline walkthrough; not a live result or sign-off")

    pdf.setFillColor(INK)
    pdf.rect(0, HEIGHT - 151, WIDTH, 151, fill=1, stroke=0)
    text(
        pdf, LEFT, HEIGHT - 42, "FILE MANAGEMENT ASSISTANT  /  TEAM 11  /  WEEK 13",
        8.7, LIGHT, "Courier-Bold",
    )
    pdf.setFillColor(LIME)
    pdf.roundRect(WIDTH - LEFT - 105, HEIGHT - 50, 105, 21, 4, fill=1, stroke=0)
    text(pdf, WIDTH - LEFT - 96, HEIGHT - 43.3, "OFFLINE CUE CARD", 9, INK, "Courier-Bold")
    text(pdf, LEFT, HEIGHT - 93, "PDF fallback", 39, colors.white, "Helvetica-Bold")
    text(
        pdf, LEFT, HEIGHT - 121, "A walkthrough for text-layer PDFs and keyword search.", 13, LIGHT,
    )
    text(pdf, LEFT, HEIGHT - 138, "Not a live run, recording, or release sign-off.", 10, LIGHT)

    text(pdf, LEFT, 660, "Five steps to verify", 22, INK, "Helvetica-Bold")
    steps = [
        (
            "Check the real stack",
            "Record the candidate SHA and config (<b>FRONTEND_DATA_MODE=api</b>; embeddings "
            "disabled for fallback). Check <b>http://127.0.0.1:8000/health/ready</b> before "
            "opening the browser.",
        ),
        (
            "Authorize and scan the read-only corpus",
            "At <b>http://127.0.0.1:3000/select</b>, authorize <b>corpus</b> and scan; save "
            "root/job IDs. Look for <b>basic_ready</b> plus <b>no_text_layer</b> on "
            "<b>abnormal/no_text_layer.pdf</b>.",
        ),
        (
            "Search, open and match the source",
            "Search <b>Marker01P1</b> in keyword mode and open the hit. Match file/version/chunk "
            "IDs in <b>POST /search</b> and <b>GET /evidence/{chunk_id}</b>; verify physical "
            "page 1 and its text.",
        ),
        (
            "Re-scan and restart with the same data volume",
            "Confirm unchanged sources add no new versions/extract/index jobs; a new scan ID is "
            "expected. After restart, reopen the evidence and compare source SHA-256. Keep the "
            "data volume.",
        ),
        (
            "Save the run evidence",
            "Keep timestamped browser and API evidence, worker logs or metrics, and failure/skip "
            "notes. Record C and D outcomes for that exact SHA; this card records neither outcome.",
        ),
    ]
    for number, (title, details) in enumerate(steps, start=1):
        step(pdf, 630 - (number - 1) * 53, number, title, details)

    pdf.setFillColor(TINT)
    pdf.roundRect(LEFT, 218, CONTENT, 151, 8, fill=1, stroke=0)
    offset = LEFT + 16
    text(
        pdf, offset, 348, "STATIC SOURCE EXCERPT  /  PHYSICAL PAGE 1 OF 2",
        9.5, ACCENT, "Courier-Bold",
    )
    text(pdf, offset, 328, record["fixture_path"], 9.2, MUTED, "Courier")
    for index, line in enumerate(excerpt):
        has_marker = MARKER in line
        text(pdf, offset, 306 - index * 14, line, 10.2, ACCENT if has_marker else INK,
             "Courier-Bold" if has_marker else "Courier")
    text(pdf, offset, 232, "SHA-256  " + record["sha256"], 8.1, MUTED, "Courier")

    text(pdf, LEFT, 189, "If the live demo is unavailable", 15, INK, "Helvetica-Bold")
    paragraph(
        pdf, LEFT, 175,
        "Use this card to explain the flow and show the static fixture excerpt. Label it as an "
        "illustration; only a recording of the same verified build demonstrates a prior run. "
        "Keyword mode does not prove the course's integrated AI step; show and verify the model "
        "separately if ready, or report it as unverified.",
        CONTENT,
    )
    paragraph(
        pdf, LEFT, 115,
        "<b>Scope:</b> text-layer PDF only for this walkthrough; no OCR, visual model or media "
        "processing. No current candidate or C/D sign-off is asserted. TXT, MD and DOCX are not "
        "covered here.",
        CONTENT,
    )
    pdf.setStrokeColor(RULE)
    pdf.setLineWidth(0.6)
    pdf.line(LEFT, 62, WIDTH - LEFT, 62)
    text(pdf, LEFT, 46, "Fixture source commit: " + FIXTURE_COMMIT, 8.4, MUTED, "Courier")
    text(pdf, WIDTH - LEFT - 11, 46, "01", 9, ACCENT, "Courier-Bold")
    pdf.showPage()
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
