#!/usr/bin/env python3
"""Генерирует иконку приложения (атом «AI» на скруглённой плитке).

Исходник — scripts/icon-src.png (PNG с альфой). Выход — static/:
  favicon.svg        — PNG внутри SVG (favicon + лого в шапке)
  favicon.ico        — 16/32/48/64
  icon.png           — 568x568, «any»-иконка PWA
  icon-maskable.png  — плитка во весь квадрат (safe zone для maskable)
  apple-icon.png     — 180x180 (iOS не читает альфу — плитка как фон)
"""
import base64
import io
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "icon-src.png"
OUT = ROOT / "static"

atom = Image.open(SRC).convert("RGBA")

# Плитка: диагональный градиент циан → тёмная бирюза (палитра иконки)
C_TL = (0, 188, 212)    # #00BCD4
C_BR = (0, 121, 107)    # #00796B
RADIUS = 0.225          # радиус углов, доля размера (iOS-подобный)
ICON_SCALE = 0.86       # атом внутри плитки


def gradient(size):
    """Диагональный градиент C_TL → C_BR: строим его на холсте
    шириной с диагональ плитки, поворачиваем и кадрируем центр —
    полос от поворота не остаётся."""
    d = math.ceil(size * math.sqrt(2)) + 2
    g = Image.linear_gradient("L").resize((d, d), Image.BICUBIC)
    g = g.rotate(45, expand=False, resample=Image.BICUBIC)
    off = (d - size) // 2
    g = g.crop((off, off, off + size, off + size))
    return ImageOps.colorize(g, black=C_TL, white=C_BR).convert("RGBA")


def rounded_mask(size, radius):
    big = size * 4
    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, big - 1, big - 1],
                        radius=big * radius, fill=255)
    return m.resize((size, size), Image.LANCZOS)


def tile(size, radius=RADIUS, scale=ICON_SCALE):
    """Атом на скруглённой градиентной плитке; radius=0 — квадрат."""
    t = gradient(size)
    t.putalpha(rounded_mask(size, radius) if radius
               else Image.new("L", (size, size), 255))
    inner = round(size * scale)
    a = atom.resize((inner, inner), Image.LANCZOS)
    t.paste(a, ((size - inner) // 2, (size - inner) // 2), a)
    return t


# --- favicon.svg: растр внутри SVG (одна геометрия на все случаи) ----------
buf = io.BytesIO()
tile(128).save(buf, format="PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
(OUT / "favicon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'viewBox="0 0 128 128">\n'
    f'  <image width="128" height="128" '
    f'href="data:image/png;base64,{b64}"/>\n</svg>\n')

# --- PNG-иконки -------------------------------------------------------------
# icon.png и apple-icon.png — плитка во весь квадрат (radius=0): у Windows
# и iOS нет прозрачных углов, которые те подставили бы белым/чёрным фоном.
tile(568, radius=0, scale=0.78).save(OUT / "icon.png")
# maskable обрезается ОСью в круг/сквиркл — атом мельче, в safe zone
tile(568, radius=0, scale=0.70).save(OUT / "icon-maskable.png")
tile(180, radius=0, scale=0.78).convert("RGB").save(OUT / "apple-icon.png")
tile(256).save(OUT / "favicon.ico",
               sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("done ->", OUT)
