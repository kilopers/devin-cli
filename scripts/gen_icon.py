#!/usr/bin/env python3
"""Генерирует иконку приложения (атом с «AI») во всех форматах.

Исходник — scripts/icon-src.png (PNG с альфой). Выход — static/:
  favicon.svg        — PNG внутри SVG (favicon + лого в шапке)
  favicon.ico        — 16/32/48/64
  icon.png           — 568x568, «any»-иконка PWA
  icon-maskable.png  — та же с полем ~12% (safe zone для maskable)
  apple-icon.png     — 180x180 на белом фоне (iOS не читает альфу)
"""
import base64
import io
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "icon-src.png"
OUT = ROOT / "static"

img = Image.open(SRC).convert("RGBA")


def flat(size, bg=(255, 255, 255), scale=1.0):
    """Иконка size×size; scale<1 — с полем (safe zone); bg=None → прозрачная."""
    inner = round(size * scale)
    icon = img.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(icon, ((size - inner) // 2, (size - inner) // 2), icon)
    if bg is None:
        return canvas
    out = Image.new("RGBA", (size, size), bg + (255,))
    out.paste(canvas, (0, 0), canvas)
    return out


# --- favicon.svg: растр внутри SVG (одна геометрия на все случаи) ----------
small = img.resize((128, 128), Image.LANCZOS)
buf = io.BytesIO()
small.save(buf, format="PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
(OUT / "favicon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'viewBox="0 0 128 128">\n'
    f'  <image width="128" height="128" '
    f'href="data:image/png;base64,{b64}"/>\n</svg>\n')

# --- PNG-иконки -------------------------------------------------------------
flat(568).save(OUT / "icon.png")
flat(568, bg=(255, 255, 255), scale=0.76).save(OUT / "icon-maskable.png")
flat(180, bg=(255, 255, 255)).convert("RGB").save(OUT / "apple-icon.png")
flat(64).save(OUT / "favicon.ico",
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("done ->", OUT)
