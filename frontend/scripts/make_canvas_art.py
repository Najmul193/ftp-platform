"""Generate the textured shapes that frame the canvas.

Modelled on Oracle Redwood's background art: a few large organic shapes that
bleed off the edges of the page, each filled with a hand-drawn "data texture"
(wavy contour lines, rows of dots, scattered pebbles), in one hue at low
strength. They frame the content; they never sit behind it.

Each shape is written once per theme with its ink baked in, so the page can use
it as a plain background image (and so `background-attachment: fixed` works).

    python3 frontend/scripts/make_canvas_art.py

Standard library only; the seed is fixed, so the output is reproducible. Tune
the constants below and re-run to change density, size or strength.
"""
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "public"

#: (colour, group opacity) per theme. Brand-tinted: indigo and green from the
#: Data Edge logo, kept faint enough that the canvas still reads as grey.
INK = {
    "light": {"contour": ("#2f35a8", 0.16), "dots": ("#2a9a2a", 0.22)},
    "dark":  {"contour": ("#8b90f0", 0.24), "dots": ("#3ccb6a", 0.20)},
}


def blob_path(rng, cx, cy, rx, ry, points=11, wobble=0.2):
    """A smooth closed organic outline: noisy polar radii through Catmull-Rom."""
    pts = []
    for i in range(points):
        a = 2 * math.pi * i / points
        k = 1 + rng.uniform(-wobble, wobble)
        pts.append((cx + math.cos(a) * rx * k, cy + math.sin(a) * ry * k))
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    n = len(pts)
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return "".join(d) + "Z"


def svg(w, h, body, clip=None):
    defs = f'<defs><clipPath id="c"><path d="{clip}"/></clipPath></defs>' if clip else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">{defs}{body}</svg>\n')


def contour(rng, colour, opacity, w=780, h=440):
    """Wood-grain / topographic lines: near-parallel, undulating, swelling
    round a knot the way grain does, with the occasional pen lift so they read
    as drawn rather than plotted."""
    clip = blob_path(rng, w * 0.5, h * 0.52, w * 0.48, h * 0.45, points=8, wobble=0.28)
    lines = []
    f1, f2 = rng.uniform(0.006, 0.009), rng.uniform(0.018, 0.026)
    kx, ky, kr = w * 0.62, h * 0.46, 70.0          # the knot the grain bends round
    for row, y0 in enumerate(range(4, h, 6)):
        ph1 = row * 0.07 + rng.uniform(-0.05, 0.05)
        ph2 = row * 0.19
        amp = 9 + 6 * math.sin(row * 0.13)
        seg, x = [], 0.0
        while x <= w:
            # Lines above the knot bow up, lines below bow down, fading with
            # distance -- grain parting round an obstacle.
            dy = y0 - ky
            push = 26 * math.exp(-((x - kx) ** 2) / (2 * 95 ** 2)) \
                * math.exp(-(dy ** 2) / (2 * kr ** 2)) * (1 if dy >= 0 else -1)
            y = (y0 + push + amp * math.sin(x * f1 + ph1) + 2.2 * math.sin(x * f2 + ph2)
                 + rng.uniform(-0.35, 0.35))
            seg.append(f"{x:.0f},{y:.1f}")
            x += 8
            if rng.random() < 0.012 and len(seg) > 3:   # a pen lift
                lines.append((seg, rng.uniform(0.8, 1.4)))
                seg, x = [], x + rng.uniform(10, 26)
        if len(seg) > 1:
            lines.append((seg, rng.uniform(0.8, 1.4)))
    body = "".join(
        f'<polyline points="{" ".join(p)}" stroke-width="{sw:.2f}"/>' for p, sw in lines)
    return svg(w, h, (f'<g clip-path="url(#c)" fill="none" stroke="{colour}" '
                      f'stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}">'
                      f'{body}</g>'), clip)


def dots(rng, colour, opacity, w=600, h=380):
    """Rows of dots in one blob, and beside it a soft solid shape strewn with
    pebble outlines -- the two textures Oracle pairs most often."""
    clip = blob_path(rng, w * 0.36, h * 0.44, w * 0.34, h * 0.40, points=8, wobble=0.26)
    out = []
    for row, y0 in enumerate(range(8, h, 7)):
        x = rng.uniform(0, 4)
        while x < w * 0.75:
            if rng.random() > 0.08:
                y = y0 + 1.4 * math.sin(x * 0.02 + row * 0.3)
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rng.uniform(0.9, 1.6):.2f}"/>')
            x += rng.uniform(4.5, 7)
    dot_rows = f'<g clip-path="url(#c)" fill="{colour}">{"".join(out)}</g>'

    # The soft shape sits lower right, partly under the pebbles.
    soft = blob_path(rng, w * 0.74, h * 0.72, w * 0.22, h * 0.17, points=9, wobble=0.25)
    pebbles, placed = [], []
    tries = 0
    while len(pebbles) < 46 and tries < 4000:
        tries += 1
        px, py = rng.uniform(w * 0.52, w * 0.97), rng.uniform(h * 0.45, h * 0.97)
        if any((px - qx) ** 2 + (py - qy) ** 2 < 15 ** 2 for qx, qy in placed):
            continue
        placed.append((px, py))
        pebbles.append(
            f'<ellipse cx="{px:.1f}" cy="{py:.1f}" rx="{rng.uniform(3, 5.5):.1f}" '
            f'ry="{rng.uniform(2.4, 4.2):.1f}" '
            f'transform="rotate({rng.uniform(-60, 60):.0f} {px:.1f} {py:.1f})"/>')
    rest = (f'<path d="{soft}" fill="{colour}" opacity="0.45"/>'
            f'<g fill="none" stroke="{colour}" stroke-width="1.1">{"".join(pebbles)}</g>')
    return svg(w, h, f'<g opacity="{opacity}">{dot_rows}{rest}</g>', clip)


def sprinkle(rng, colour, opacity, w=340, h=230):
    """A patch of dots that sits beside the contour grain in the same ink.

    No hard edge: dots thin out and shrink towards an irregular border, so the
    patch dissolves into the canvas and into the grain it overlaps rather than
    stopping at an outline."""
    cx, cy = w / 2, h / 2
    ph1, ph2 = rng.uniform(0, 6.3), rng.uniform(0, 6.3)
    out = []
    for row, y0 in enumerate(range(4, h, 7)):
        x = rng.uniform(0, 5)
        while x < w:
            y = y0 + 1.3 * math.sin(x * 0.024 + row * 0.35)
            a = math.atan2((y - cy) / h, (x - cx) / w)
            # Organic border: the radius wobbles with angle.
            edge = 1 + 0.16 * math.sin(3 * a + ph1) + 0.08 * math.sin(5 * a + ph2)
            d = math.hypot((x - cx) / (w / 2), (y - cy) / (h / 2)) / edge
            keep = max(0.0, 1 - d * d) ** 1.4          # dense core, feathered rim
            if rng.random() < keep:
                r = 0.7 + 0.95 * (1 - min(d, 1)) + rng.uniform(-0.15, 0.15)
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}"/>')
            x += rng.uniform(4.5, 6.5)
    return svg(w, h, f'<g fill="{colour}" opacity="{opacity}">{"".join(out)}</g>')


def main():
    for theme, inks in INK.items():
        # Same seed per shape in both themes, so light and dark are one drawing.
        (OUT / f"canvas-contour-{theme}.svg").write_text(
            contour(random.Random(7), *inks["contour"]))
        (OUT / f"canvas-dots-{theme}.svg").write_text(
            dots(random.Random(11), *inks["dots"]))
        # Same indigo as the grain beside it, a touch stronger since dots
        # carry less ink than lines.
        colour, opacity = inks["contour"]
        (OUT / f"canvas-sprinkle-{theme}.svg").write_text(
            sprinkle(random.Random(23), colour, round(opacity * 1.25, 3)))
    for p in sorted(OUT.glob("canvas-*.svg")):
        print(f"{p.name}: {p.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
