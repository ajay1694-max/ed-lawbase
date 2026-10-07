#!/usr/bin/env python3
"""make_icons.py - draw the LawBase app icons (white balance scale on navy) into app/static/.

    python deploy/make_icons.py
Writes icon-192.png, icon-512.png, icon-maskable-512.png (artwork inside the 80% safe zone), apple-touch-icon.png
and favicon.png. Drawn at 4x and downscaled for clean edges.
"""
import os
from PIL import Image, ImageDraw

NAVY, WHITE, GOLD = (31, 58, 95), (255, 255, 255), (231, 190, 92)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static")


def scale_art(size, inset):
    """Balance scale centred in a size x size canvas; inset = fraction of the edge kept clear on each side."""
    S = size * 4
    im = Image.new("RGBA", (S, S), NAVY + (255,))
    d = ImageDraw.Draw(im)
    box = S * (1 - 2 * inset)
    o = S * inset
    u = box / 100.0                      # artwork drawn on a 100 x 100 grid inside the safe box
    P = lambda x, y: (o + x * u, o + y * u)
    w = 3.2 * u
    d.line([P(50, 16), P(50, 82)], fill=WHITE, width=round(w * 1.3))             # pillar
    d.rounded_rectangle([P(32, 80), P(68, 86)], radius=2 * u, fill=WHITE)        # base
    d.line([P(18, 28), P(82, 28)], fill=WHITE, width=round(w * 1.2))             # beam
    d.ellipse([P(46, 11), P(54, 19)], fill=GOLD)                                  # finial
    for cx in (22, 78):                                                            # two pans on chains
        d.line([P(cx, 28), P(cx - 11, 52)], fill=WHITE, width=round(w * 0.7))
        d.line([P(cx, 28), P(cx + 11, 52)], fill=WHITE, width=round(w * 0.7))
        d.chord([P(cx - 15, 42), P(cx + 15, 62)], start=0, end=180, fill=WHITE)
    return im.resize((size, size), Image.LANCZOS)


def rounded(im, radius_frac=0.22):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius=int(im.size[0] * radius_frac), fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, (0, 0), m)
    return out


if __name__ == "__main__":
    rounded(scale_art(192, 0.12)).save(os.path.join(OUT, "icon-192.png"))
    rounded(scale_art(512, 0.12)).save(os.path.join(OUT, "icon-512.png"))
    scale_art(512, 0.2).convert("RGB").save(os.path.join(OUT, "icon-maskable-512.png"))   # full-bleed, 80% safe zone
    scale_art(180, 0.12).convert("RGB").save(os.path.join(OUT, "apple-touch-icon.png"))
    rounded(scale_art(64, 0.08)).save(os.path.join(OUT, "favicon.png"))
    print("icons written to", OUT)
