"""
Genera la web app (cartella web/) dalla dashboard di claude.ai (dashboard/) e da web_src/.

  python -m cloud.build_web

dashboard/index.html e' un frammento con <style> e <script> in linea: qui stili e script finiscono in file
separati (la CSP della web app ammette solo script dello stesso sito) e il frammento va nell'involucro
web_src/shell.html. Restano fuori le immagini della card "La carica" (arrivano cifrate dentro data.bin) e
ogni riferimento personale. Il service worker riceve l'elenco dei file e l'impronta della build.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dashboard"
SHELL = ROOT / "web_src"
OUT = ROOT / "web"

EXCLUDE = re.compile(r"^carica_img_\d+\.js$")
# testi da adattare fuori da claude.ai; quelli personali stanno in cloud/.web_replacements.json
# ({"file": [["vecchio", "nuovo"], ...]}), che non viene pubblicato
REPLACE = {
    "index.html": [(" Apri la chat accanto alla dashboard per fare domande sui tuoi dati.", "")],
}
_LOCAL = ROOT / "cloud" / ".web_replacements.json"
if _LOCAL.exists():
    for _f, _pairs in json.loads(_LOCAL.read_text(encoding="utf-8")).items():
        REPLACE.setdefault(_f, []).extend(tuple(p) for p in _pairs)
TOKEN = re.compile(r'<link rel="stylesheet" href="([^"]+)">|<style>(.*?)</style>|<script>(.*?)</script>|<script src="([^"]+)"></script>', re.S)


def fix(name: str, text: str) -> str:
    for old, new in REPLACE.get(name, []):
        if old not in text:
            raise SystemExit(f"{name}: testo da sostituire non trovato ({old[:40]}...)")
        text = text.replace(old, new)
    return text


def icons() -> None:
    """Icona dell'app: web_src/app-icon.png (quadrata, fondo nero) se c'e', altrimenti un tracciato del battito al neon."""
    from PIL import Image, ImageDraw, ImageFilter
    custom = SHELL / "app-icon.png"
    if custom.exists():
        src = Image.open(custom).convert("RGBA")
        side = min(src.size)
        src = src.crop(((src.width - side) // 2, (src.height - side) // 2, (src.width + side) // 2, (src.height + side) // 2))
        img = Image.new("RGB", src.size, (0, 0, 0))
        img.paste(src, mask=src.getchannel("A"))          # iOS non accetta trasparenze: fondo nero pieno
        for size in (180, 192, 512):
            img.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)
        return
    base = 1024
    pts = [(2, 12), (6, 12), (8.5, 7), (12.5, 17), (15, 12), (22, 12)]
    img = Image.new("RGB", (base, base), (7, 10, 18))
    glow = Image.new("RGB", (base, base), (0, 0, 0))
    s = base / 24 * 0.72
    off = base * 0.14
    xy = [(off + x * s, off + y * s - s * 0.0 + base * 0.0) for x, y in pts]
    ImageDraw.Draw(glow).line(xy, fill=(34, 229, 255), width=int(base * 0.06), joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(base * 0.035))
    img = Image.blend(img, glow, 0.9)
    ImageDraw.Draw(img).line(xy, fill=(200, 250, 255), width=int(base * 0.028), joint="curve")
    for size in (180, 192, 512):
        img.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    page = fix("index.html", (SRC / "index.html").read_text(encoding="utf-8"))

    styles, scripts, inline_css, n = [], [], [], 0

    def take(m: re.Match) -> str:
        nonlocal n
        href, css, js, src = m.groups()
        if href:
            styles.append(href)
        elif css is not None:
            inline_css.append(css.strip())
        elif js is not None:
            n += 1
            (OUT / f"inline-{n}.js").write_text(js.strip() + "\n", encoding="utf-8")
            scripts.append(f"inline-{n}.js")
        elif src and not EXCLUDE.match(src):
            scripts.append(src)
        return ""

    body = TOKEN.sub(take, page).strip()
    if inline_css:
        (OUT / "page.css").write_text("\n\n".join(inline_css) + "\n", encoding="utf-8")
        styles.append("page.css")
    for f in {*styles, *scripts} - {"page.css"} - {s for s in scripts if s.startswith("inline-")}:
        (OUT / f).write_text(fix(f, (SRC / f).read_text(encoding="utf-8")), encoding="utf-8")

    for f in ("app.js", "base.css", "manifest.webmanifest"):
        shutil.copy2(SHELL / f, OUT / f)
    shutil.copy2(SHELL / "vendor" / "d3-7.9.0.min.js", OUT / "d3.min.js")
    icons()

    tags_css = "\n".join(f'<link rel="stylesheet" href="{s}">' for s in styles)
    order = ["d3.min.js", "app.js", *scripts]
    tags_js = "\n".join(f'<script src="{s}"></script>' for s in order)
    html = (SHELL / "shell.html").read_text(encoding="utf-8")
    html = html.replace("{{STYLES}}", tags_css).replace("{{BODY}}", body).replace("{{SCRIPTS}}", tags_js)
    (OUT / "index.html").write_text(html, encoding="utf-8")

    files = sorted(p.name for p in OUT.iterdir() if p.is_file())
    digest = hashlib.sha256(b"".join((OUT / f).read_bytes() for f in files)).hexdigest()[:12]
    sw = (SHELL / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("{{VERSION}}", digest).replace("{{FILES}}", json.dumps(["./", *files]))
    (OUT / "sw.js").write_text(sw, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"web/: {len(files) + 1} file, build {digest}")


if __name__ == "__main__":
    main()
