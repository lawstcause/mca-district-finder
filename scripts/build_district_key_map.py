#!/usr/bin/env python3
"""Build a cleaned MCA neighborhood map with district tints and a key.

Source: 23_MCA_NEIGHBORHOODmap.pdf. Streets are rebuilt as solid white lines
with all map labels removed. District numbers and the key stay.
"""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

ROOT = Path(__file__).resolve().parents[1]
PDF_SRC = Path("/Users/lawrenceuhling/Downloads/23_MCA_NEIGHBORHOODmap.pdf")
GEO_SRC = ROOT / "public" / "maps" / "mca-delegates-geometry.png"
OUT_DIR = ROOT / "public" / "maps"
PREVIEW_DIR = Path("/tmp/mca_key_preview")
DOWNLOADS = Path("/Users/lawrenceuhling/Downloads")

# Geometry was traced on a 1248×1929 render of this page; shift to match 3301×5101.
ALIGN_DY = 32

FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"
GILL = "/System/Library/Fonts/Supplemental/GillSans.ttc"
DIN = "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"

# Interior points on mca-delegates-geometry.png (1248×1929), one per blob.
SEED_XY = {
    1: (772, 1374),
    2: (183, 1540),
    3: (329, 1473),
    4: (321, 1678),
    5: (704, 1530),
    6: (381, 1308),
    7: (374, 1136),
    8: (358, 853),
    9: (383, 574),
    10: (483, 351),
    11: (640, 267),
}

# Print pastels — readable, not neon
PASTELS = {
    1: (158, 166, 98),
    2: (176, 208, 156),
    3: (216, 164, 196),
    4: (228, 188, 128),
    5: (156, 204, 220),
    6: (232, 220, 132),
    7: (228, 168, 160),
    8: (176, 168, 212),
    9: (204, 172, 104),
    10: (140, 204, 196),
    11: (228, 172, 204),
}

# Official names from the handwritten MCA delegate key
DISTRICTS = [
    (1, "North Eastbridge", "& Bluff Lake"),
    (2, "East 29th Avenue", ""),
    (3, "Westerly Creek", ""),
    (4, "South End", ""),
    (5, "East Bridge", ""),
    (6, "CP North & CP West", ""),
    (7, "Center Field", ""),
    (8, "Conservatory Green", ""),
    (9, "Willow Park East", "& Wicker Park"),
    (10, "Beeler Park", ""),
    (11, "North End Neighborhood", ""),
]


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


def load_neighborhood() -> Image.Image:
    reader = PdfReader(str(PDF_SRC))
    page = reader.pages[0]
    data = page["/Resources"]["/XObject"]["/image"].get_object().get_data()
    return Image.open(io.BytesIO(data)).convert("RGB")


def classify_geometry(geo: np.ndarray) -> np.ndarray:
    """Flood-fill each solid district blob from a known interior point."""
    h, w = geo.shape[:2]
    ids = np.zeros((h, w), dtype=np.uint8)
    src = (geo // 32 * 32).astype(np.uint8)
    for did, (x, y) in SEED_XY.items():
        if not (0 <= x < w and 0 <= y < h):
            raise SystemExit(f"seed D{did} out of bounds {(x, y)}")
        mask = np.zeros((h + 2, w + 2), np.uint8)
        flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY
        cv2.floodFill(
            src.copy(),
            mask,
            (x, y),
            0,
            loDiff=(12, 12, 12),
            upDiff=(12, 12, 12),
            flags=flags,
        )
        blob = mask[1:-1, 1:-1] == 255
        n = int(blob.sum())
        if n < 5000:
            raise SystemExit(f"D{did} flood at {(x, y)} only {n} px, color={tuple(geo[y, x])}")
        overlap = int(((ids > 0) & blob).sum())
        if overlap > 200:
            raise SystemExit(f"D{did} flood overlaps existing ids by {overlap} px")
        ids[blob] = did
    kernel = np.ones((7, 7), np.uint8)
    grown = ids.copy()
    for did in range(1, 12):
        m = cv2.dilate((ids == did).astype(np.uint8), kernel)
        grown[(grown == 0) & (m == 1)] = did
    return grown


def grow_into_gray(ids: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Assign leftover unlabeled gray blocks to the neighboring district."""
    rgb = base.astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    is_park = (g > r + 12) & (g > b + 8) & (g > 70)
    gray = (chroma < 30) & (lum >= 170) & (lum <= 232) & ~is_park
    out = ids.copy()
    kernel = np.ones((25, 25), np.uint8)
    for _ in range(4):
        for did in range(1, 12):
            grow = cv2.dilate((out == did).astype(np.uint8), kernel) > 0
            out[(out == 0) & grow & gray] = did
    return out


def upsample_ids(ids: np.ndarray, size: tuple[int, int], dy: int) -> np.ndarray:
    w, h = size
    hi = cv2.resize(ids, (w, h), interpolation=cv2.INTER_NEAREST)
    if dy == 0:
        return hi
    aligned = np.zeros_like(hi)
    if dy > 0:
        aligned[dy:, :] = hi[:-dy, :]
    else:
        aligned[:dy, :] = hi[-dy:, :]
    return aligned


def _components(mask: np.ndarray):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return n, labels, stats


def clean_map(base: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Recolor block interiors only. Keep the original street edges intact."""
    rgb = base.astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mn = np.minimum(np.minimum(r, g), b)
    mx = np.maximum(np.maximum(r, g), b)
    chroma = mx - mn
    h, w = lum.shape

    is_park = (g > r + 12) & (g > b + 8) & (g > 70)
    is_white = mn > 242
    yy = np.arange(h, dtype=np.int32)[:, None]
    is_i70 = (yy > 2688) & (yy < 2832) & (lum > 80) & (lum < 175) & (chroma < 28)

    panels = [(1078, 302, 2036, 1288), (328, 1308, 1558, 2786), (58, 2830, 3102, 4700)]
    interior = np.zeros((h, w), dtype=bool)
    frame = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in panels:
        interior[y0:y1, x0:x1] = True
        frame[y0 : y0 + 5, x0:x1] = True
        frame[y1 - 5 : y1, x0:x1] = True
        frame[y0:y1, x0 : x0 + 5] = True
        frame[y0:y1, x1 - 5 : x1] = True
    interior = interior | (cv2.dilate((ids > 0).astype(np.uint8), np.ones((8, 8), np.uint8)) > 0)
    protect_frame = frame & (lum < 120)

    logo = np.zeros((h, w), dtype=bool)
    logo[0:800, 0:980] = True
    compass = np.zeros((h, w), dtype=bool)
    compass[4480:5101, 1550:2450] = True
    protect = logo | compass | is_i70 | is_park | protect_frame

    white_f = cv2.blur(is_white.astype(np.float32), (9, 9))
    out = base.copy()
    near_white = cv2.dilate(is_white.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

    # Dark ink sitting on a street (labels) — does not expand the street rim.
    street_text = (
        (lum < 165)
        & (chroma < 22)
        & (g <= r + 8)
        & ~is_park
        & ~protect
        & interior
        & ((white_f > 0.50) | near_white)
    )
    out[street_text] = (255, 255, 255)
    # D1 and D9 still had leftover street labels; wipe ink on their streets only.
    on_st = cv2.dilate(is_white.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    ink = (lum < 180) & (chroma < 40) & (g <= r + 10) & ~is_park & ~protect & interior
    for did in (1, 9):
        zone = cv2.dilate((ids == did).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
        out[zone & ink & on_st] = (255, 255, 255)

    # True neighborhood blocks: gray, away from the street corridor.
    is_fill = (
        (chroma < 28)
        & (lum >= 175)
        & (lum <= 230)
        & (white_f < 0.32)
        & ~is_park
        & ~protect
        & interior
    )
    near_fill = cv2.dilate(is_fill.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    text_in_fill = (
        near_fill
        & (lum < 175)
        & ~is_park
        & ~protect
        & ~is_white
        & (white_f < 0.38)
        & interior
    )

    pastels = {did: np.array(col, dtype=np.float32) for did, col in PASTELS.items()}
    for did, color in pastels.items():
        solid = (is_fill | text_in_fill) & (ids == did)
        out[solid] = color.astype(np.uint8)

        # Rebuild the 1px anti-aliased rim as pastel→white instead of leftover gray.
        edge = (
            (ids == did)
            & ~is_park
            & ~protect
            & ~is_white
            & ~solid
            & interior
            & (chroma < 40)
            & (lum > 220)
            & (lum < 252)
        )
        if edge.any():
            t = np.clip((lum[edge] - 220.0) / 32.0, 0.0, 1.0).astype(np.float32)
            mixed = (1.0 - t)[:, None] * color[None, :] + t[:, None] * 255.0
            out[edge] = mixed.astype(np.uint8)

    # Park names: white letterforms on green. Do not touch street rims.
    park_frac = cv2.blur(is_park.astype(np.float32), (15, 15))
    park_name = (park_frac > 0.55) & (lum > 200) & ~is_white & ~protect
    park_name = cv2.dilate(park_name.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    park_name = park_name & ~is_white & ~protect
    if park_name.any():
        out = cv2.inpaint(out, park_name.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)

    # Sweep leftover gray and letter-speckle inside each district onto the pastel.
    # Skip white streets and the anti-aliased rim (lum >= 228).
    for did, color in PASTELS.items():
        m = (
            (ids == did)
            & ~is_park
            & ~protect
            & interior
            & (white_f < 0.35)
            & (lum < 228)
            & (chroma < 45)
        )
        dist = np.abs(out.astype(np.int16) - np.array(color, dtype=np.int16)).sum(axis=2)
        out_mn = out.min(axis=2)
        leftover = m & (dist > 40) & (out_mn < 240)
        out[leftover] = color

    # Station callout on Center Field — fill, don't chew the streets
    station = np.zeros((h, w), dtype=bool)
    station[2948:3072, 430:720] = True
    out[station & ~is_white & ~is_park & (white_f < 0.35)] = PASTELS[7]

    # Margin labels on the page, never the map frame (long ink lines)
    page_dark = ~interior & ~protect & (lum < 160) & (chroma < 80)
    n, labels, stats = _components(page_dark)
    page_text = np.zeros((h, w), dtype=bool)
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        long_side = max(bw, bh)
        short_side = max(1, min(bw, bh))
        if area > 2500:
            continue
        if long_side > 80 and long_side / short_side > 8:
            continue  # frame / leader line
        page_text[labels == i] = True
    out[page_text] = (255, 255, 255)
    return out


def district_centroids(ids: np.ndarray, base: np.ndarray) -> dict[int, tuple[int, int]]:
    rgb = base.astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mn = np.minimum(np.minimum(r, g), b)
    gch = rgb[:, :, 1]
    is_park = (gch > r + 12) & (gch > b + 8) & (gch > 70)
    is_white = mn > 240
    residential = (ids > 0) & ~is_park & ~is_white
    cents: dict[int, tuple[int, int]] = {}
    for did in range(1, 12):
        ys, xs = np.where(residential & (ids == did))
        if len(xs) < 200:
            ys, xs = np.where(ids == did)
        if len(xs) == 0:
            continue
        # median is more stable than mean on L-shaped districts
        cents[did] = (int(np.median(xs)), int(np.median(ys)))
    return cents


def draw_badge(draw: ImageDraw.ImageDraw, xy: tuple[int, int], did: int, radius: int = 52):
    x, y = xy
    fill = PASTELS[did]
    # contrast for the numeral
    lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    fg = (20, 28, 22) if lum > 160 else (255, 255, 255)
    draw.ellipse((x - radius - 4, y - radius - 4, x + radius + 4, y + radius + 4), fill=(255, 255, 255))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    f = font(DIN, int(radius * 1.15))
    label = str(did)
    bb = draw.textbbox((0, 0), label, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((x - tw / 2, y - th / 2 - bb[1] * 0.15), label, font=f, fill=fg)


def draw_key(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    # Upper-right white field, left of the page edge, above I-70
    x0, y0 = 2148, 168
    w, h = 1020, 2480
    # card
    draw.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=28, fill=(255, 255, 255), outline=(28, 28, 28), width=4)

    title = font(FUTURA, 54, index=2)
    sub = font(GILL, 26, index=0)
    name_f = font(GILL, 36, index=4)
    name2_f = font(GILL, 30, index=0)
    foot = font(GILL, 22, index=7)

    draw.text((x0 + 56, y0 + 44), "DISTRICT KEY", font=title, fill=(20, 20, 20))
    draw.text((x0 + 56, y0 + 118), "Official MCA delegate districts", font=sub, fill=(90, 90, 90))
    draw.line((x0 + 56, y0 + 168, x0 + w - 56, y0 + 168), fill=(28, 28, 28), width=2)

    row_y = y0 + 210
    row_h = 196
    for did, line1, line2 in DISTRICTS:
        cy = row_y + 78
        cx = x0 + 118
        draw_badge(draw, (cx, cy), did, radius=48)
        tx = x0 + 196
        draw.text((tx, row_y + (42 if line2 else 58)), line1, font=name_f, fill=(22, 22, 22))
        if line2:
            draw.text((tx, row_y + 92), line2, font=name2_f, fill=(70, 70, 70))
        # divider
        draw.line((tx, row_y + row_h - 8, x0 + w - 56, row_y + row_h - 8), fill=(230, 230, 230), width=1)
        row_y += row_h

    note = "Colors mark the official districts.\nParks stay green. Match a number on the map."
    draw.multiline_text((x0 + 56, y0 + h - 130), note, font=foot, fill=(110, 110, 110), spacing=6)


def nudge_badges(cents: dict[int, tuple[int, int]]) -> dict[int, tuple[int, int]]:
    """Keep numbers on open fill, off park labels and the key card."""
    nudged = dict(cents)
    # Hand nudges in source-pixel space after looking at the schematic
    tweaks = {
        1: (2520, 4020),  # far-east Eastbridge
        2: (420, 4120),  # west of CPB, south of MLK
        3: (280, 3780),  # 29th Drive / Westerly Creek
        4: (720, 4480),  # South End
        5: (1680, 4080),  # 26th Ave Park / Eastbridge
        6: (520, 3480),  # 35th Ave
        7: (420, 3180),  # station / Center Field
        8: (820, 2100),  # Conservatory Green
        9: (700, 1480),  # Willow / Wicker
        10: (1180, 780),  # Beeler Park (west north inset)
        11: (1680, 520),  # North End (east north inset)
    }
    nudged.update(tweaks)
    return nudged


def save_previews(img: Image.Image) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    small = img.resize((1100, int(1100 * img.height / img.width)), Image.Resampling.LANCZOS)
    small.save(PREVIEW_DIR / "overview.jpg", quality=90)
    crops = {
        "north": (900, 80, 2300, 1320),
        "mid": (80, 1100, 1700, 2700),
        "south": (40, 2780, 2100, 4780),
        "east": (1400, 3100, 3280, 4700),
        "d1": (2100, 3680, 3100, 4300),
        "d9": (300, 1280, 1600, 1900),
        "key": (2080, 120, 3280, 2720),
        "logo": (40, 40, 980, 560),
    }
    for name, box in crops.items():
        img.crop(box).save(PREVIEW_DIR / f"{name}.jpg", quality=92)


def write_pdf(png_path: Path, pdf_path: Path, page_w: float, page_h: float) -> None:
    c = pdfcanvas.Canvas(str(pdf_path), pagesize=(page_w, page_h))
    c.drawImage(ImageReader(str(png_path)), 0, 0, width=page_w, height=page_h, preserveAspectRatio=True, anchor="c")
    c.save()


def main() -> None:
    print("loading neighborhood PDF…")
    nb = load_neighborhood()
    W, H = nb.size
    print("page", W, H)

    geo = np.array(Image.open(GEO_SRC).convert("RGB"))
    ids_small = classify_geometry(geo)
    for did in range(1, 12):
        print(f"  D{did:02d} pixels {int((ids_small == did).sum())}")
    ids = upsample_ids(ids_small, (W, H), ALIGN_DY)
    ids = grow_into_gray(ids, np.array(nb))

    # Center Field parcel west of the station is inside D7 on the official map
    # but sits just outside the traced blob.
    gray = np.all(np.abs(np.array(nb).astype(np.int16) - np.array([213, 212, 207])) < 18, axis=2)
    ids[2920:3380, 50:560][(ids[2920:3380, 50:560] == 0) & gray[2920:3380, 50:560]] = 7

    print("cleaning streets and labels…")
    colored = clean_map(np.array(nb), ids)
    img = Image.fromarray(colored)

    cents = district_centroids(ids, np.array(nb))
    print("raw centroids", cents)
    cents = nudge_badges(cents)

    draw_key(img)
    draw = ImageDraw.Draw(img)
    for did, xy in cents.items():
        draw_badge(draw, xy, did, radius=54)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUT_DIR / "mca-district-key.png"
    jpg = OUT_DIR / "mca-district-key.jpg"
    jpg_sm = OUT_DIR / "mca-delegates-streets-sm.jpg"
    pdf_out = OUT_DIR / "mca-district-key.pdf"
    dl_pdf = DOWNLOADS / "MCA_Central_Park_District_Map.pdf"
    dl_png = DOWNLOADS / "MCA_Central_Park_District_Map.png"

    print("saving", png)
    img.save(png, optimize=True)
    preview = img.resize((1400, int(1400 * H / W)), Image.Resampling.LANCZOS)
    preview.save(jpg, quality=88, optimize=True)
    preview.save(jpg_sm, quality=82, optimize=True)

    reader = PdfReader(str(PDF_SRC))
    box = reader.pages[0].mediabox
    page_w, page_h = float(box.width), float(box.height)
    write_pdf(png, pdf_out, page_w, page_h)
    write_pdf(png, dl_pdf, page_w, page_h)
    img.save(dl_png, optimize=True)

    save_previews(img)
    print("wrote", png, jpg, pdf_out, dl_pdf)


if __name__ == "__main__":
    main()
