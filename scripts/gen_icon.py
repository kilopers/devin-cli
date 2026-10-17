#!/usr/bin/env python3
"""Генерирует иконку приложения (шестерёнка + </>) во всех форматах."""
import math
from PIL import Image, ImageDraw, ImageFilter

OUT = "/Users/yura/Desktop/work/devincli/static"

# Цвета из референса: фиолет градиент в синий
C_TL = (167, 106, 245)   # верхний левый — фиолет
C_BR = (76, 122, 240)    # нижний правый — синий
C_GLYPH = (207, 215, 255)  # </> — светло-сиреневый

S = 1024            # базовый холст
SS = 4              # суперсэмплинг для сглаживания
CX = CY = S / 2
R_OUT = 405         # радиус по вершинам зубьев (~78% — safe zone maskable)
R_IN = 315          # радиус впадин
TEETH = 10
TOOTH_HALF = math.radians(10.5)   # полуширина зуба по вершине
VALLEY_HALF = math.radians(11.5)  # полуширина впадины


def gear_points():
    """Точки контура шестерёнки (зуб = плоская вершина)."""
    pts = []
    pitch = 2 * math.pi / TEETH
    for i in range(TEETH):
        a = i * pitch
        pts += [
            (CX + R_IN * math.cos(a - VALLEY_HALF),
             CY + R_IN * math.sin(a - VALLEY_HALF)),
            (CX + R_OUT * math.cos(a - TOOTH_HALF),
             CY + R_OUT * math.sin(a - TOOTH_HALF)),
            (CX + R_OUT * math.cos(a + TOOTH_HALF),
             CY + R_OUT * math.sin(a + TOOTH_HALF)),
            (CX + R_IN * math.cos(a + VALLEY_HALF),
             CY + R_IN * math.sin(a + VALLEY_HALF)),
        ]
    return pts


GEAR = gear_points()

# Глифы </>: полилинии в координатах холста 1024
GW = 64  # толщина штриха
GLYPHS = [
    [(352, 398), (252, 512), (352, 626)],   # <
    [(452, 660), (576, 364)],               # /
    [(672, 398), (772, 512), (672, 626)],   # >
]


def gradient(size):
    """Линейный градиент по диагонали TL→BR."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = tuple(int(C_TL[c] + (C_BR[c] - C_TL[c]) * t)
                             for c in range(3))
    return img


def render_png():
    big = S * SS
    # маска шестерёнки
    mask = Image.new("L", (big, big), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(x * SS, y * SS) for x, y in GEAR], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(9 * SS))
    # градиент по маске
    img = gradient(big).convert("RGBA")
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    for line in GLYPHS:
        pts = [(x * SS, y * SS) for x, y in line]
        d.line(pts, fill=C_GLYPH, width=GW * SS, joint="curve")
        for p in pts:  # круглые концы
            r = GW * SS / 2
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=C_GLYPH)
    return img.resize((S, S), Image.LANCZOS)


def render_svg():
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in GEAR)
    shapes = []
    for line in GLYPHS:
        p = " ".join(f"{x},{y}" for x, y in line)
        shapes.append(
            f'<polyline points="{p}" fill="none" stroke="#CFD7FF" '
            f'stroke-width="{GW}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">\n'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="#A76AF5"/>'
        f'<stop offset="1" stop-color="#4C7AF0"/>'
        f'</linearGradient></defs>\n'
        f'<polygon points="{pts}" fill="url(#g)" stroke="url(#g)" '
        f'stroke-width="44" stroke-linejoin="round"/>\n'
        + "\n".join(shapes) + "\n</svg>\n")


img = render_png()
img.resize((568, 568), Image.LANCZOS).save(f"{OUT}/icon.png")
img.resize((180, 180), Image.LANCZOS).save(f"{OUT}/apple-icon.png")
img.save(f"{OUT}/favicon.ico",
         sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
with open(f"{OUT}/favicon.svg", "w") as f:
    f.write(render_svg())
print("done:", img.size)
