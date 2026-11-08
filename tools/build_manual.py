"""Build the HTML manual (docs/manual.md -> src/opencourantrp/resources/manual.html), a single dark-mode page.

The pictures of docs/img are embedded in the page, so the file can be opened from anywhere.
Needs the `markdown` package (pip install markdown).
"""

import base64
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from opencourantrp import __version__  # noqa: E402

SOURCE = ROOT / "docs" / "manual.md"
TARGET = ROOT / "src" / "opencourantrp" / "resources" / "manual.html"

CSS = """
:root { color-scheme: dark; --bg:#14171c; --panel:#1a1e25; --text:#dfe3ea; --muted:#8d96a3; --border:#2a303b;
        --accent:#4c9eff; --code:#10141a; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin:0; background:var(--bg); color:var(--text); line-height:1.6;
       font-family:"Segoe UI", system-ui, -apple-system, Arial, sans-serif; font-size:16px; }
.layout { display:flex; max-width:1240px; margin:0 auto; }
nav { position:sticky; top:0; align-self:flex-start; width:290px; flex:none; height:100vh; overflow:auto;
      padding:28px 18px 28px 24px; border-right:1px solid var(--border); font-size:14px; }
nav .brand { font-weight:600; font-size:15px; margin-bottom:14px; }
nav .brand small { display:block; color:var(--muted); font-weight:400; margin-top:2px; }
nav ul { list-style:none; margin:0; padding-left:0; }
nav ul ul { padding-left:14px; }
nav a { display:block; padding:3px 0; color:var(--muted); text-decoration:none; }
nav a:hover { color:var(--accent); }
main { flex:1; min-width:0; padding:36px 44px 80px; }
h1 { font-size:2rem; margin:0 0 .6em; }
h2 { font-size:1.45rem; margin:2.2em 0 .6em; padding-bottom:.3em; border-bottom:1px solid var(--border); }
h3 { font-size:1.15rem; margin:1.6em 0 .4em; color:#fff; }
a { color:var(--accent); }
p, li { max-width:75ch; }
img { max-width:100%; height:auto; border:1px solid var(--border); border-radius:6px; margin:10px 0; display:block; }
table { border-collapse:collapse; margin:14px 0; width:100%; font-size:15px; }
th, td { border:1px solid var(--border); padding:7px 11px; text-align:left; vertical-align:top; }
th { background:var(--panel); }
tr:nth-child(even) td { background:rgba(255,255,255,.02); }
code { background:var(--code); border:1px solid var(--border); border-radius:4px; padding:1px 5px; font-size:.9em;
       font-family:Consolas, "Cascadia Mono", monospace; }
blockquote { margin:16px 0; padding:8px 16px; background:var(--panel); border-left:3px solid var(--accent);
             border-radius:0 6px 6px 0; }
blockquote p { margin:.4em 0; }
p:has(img) { max-width:none; }
@media (max-width: 860px) { .layout { display:block; } nav { position:static; width:auto; height:auto;
        border-right:0; border-bottom:1px solid var(--border); } main { padding:24px 20px 60px; } }
@media print { nav { display:none; } body { background:#fff; color:#000; } }
"""


def embed_images(html: str) -> str:
    def inline(match: re.Match) -> str:
        path = SOURCE.parent / match.group(1)
        if not path.is_file():
            raise SystemExit(f"missing picture: {path}")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'src="data:image/png;base64,{data}"'

    return re.sub(r'src="(img/[^"]+)"', inline, html)


def main() -> None:
    md = markdown.Markdown(extensions=["toc", "tables", "fenced_code", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-3"}})
    body = md.convert(SOURCE.read_text(encoding="utf-8").replace("[TOC]\n", ""))
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenCourantRP manual</title>
<style>{CSS}</style>
</head>
<body>
<div class="layout">
<nav><div class="brand">OpenCourantRP<small>User manual - version {__version__}</small></div>{md.toc}</nav>
<main>
{embed_images(body)}
</main>
</div>
</body>
</html>
"""
    TARGET.write_text(page, encoding="utf-8")
    print("Wrote", TARGET, f"({TARGET.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
