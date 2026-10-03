"""
build_site.py - creates a book website from books.json

How it works (beginner view):
  1. Read the list of books from books.json
  2. For every book, write one HTML page  -> site/book-<id>.html
  3. Write the home page with search box  -> site/index.html
  4. Write the style (colors, layout)     -> site/style.css
Run:  python3 build_site.py      then open site/index.html
Or:   python3 build_site.py --serve   to also start a local web server
"""
import json
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "site"
SITE_NAME = "BookNest"

CSS = """
:root{--bg:#faf7f2;--card:#fff;--text:#2b2b2b;--muted:#6b6b6b;--accent:#c0392b}
*{box-sizing:border-box}
body{margin:0;font-family:Georgia,serif;background:var(--bg);color:var(--text)}
header{background:#2b2b2b;color:#fff;padding:16px;text-align:center}
header a{color:#fff;text-decoration:none;font-size:1.6rem;font-weight:bold}
main{max-width:1000px;margin:auto;padding:16px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.controls input,.controls select{flex:1;min-width:140px;padding:10px;font-size:1rem;border:1px solid #ccc;border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.card{background:var(--card);border-radius:12px;overflow:hidden;box-shadow:0 2px 8px #0002;text-decoration:none;color:inherit;display:block}
.cover{height:160px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.2rem;font-weight:bold;padding:12px;text-align:center}
.info{padding:12px}
.info h3{margin:0 0 4px;font-size:1.05rem}
.muted{color:var(--muted);font-size:.9rem}
.price{color:var(--accent);font-weight:bold}
.detail{background:var(--card);border-radius:12px;padding:16px;box-shadow:0 2px 8px #0002}
.detail .cover{height:220px;border-radius:12px;margin-bottom:16px}
.btn{display:inline-block;background:var(--accent);color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;margin-top:12px}
footer{text-align:center;color:var(--muted);padding:24px;font-size:.9rem}
.hidden{display:none}
"""

def stars(r):
    full = int(round(r))
    return "★" * full + "☆" * (5 - full)

def page(title, body, script=""):
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="stylesheet" href="style.css">
</head><body>
<header><a href="index.html">📚 {SITE_NAME}</a></header>
<main>{body}</main>
<footer>© {SITE_NAME} - made with Python</footer>
{script}
</body></html>"""

def card(b):
    return f"""<a class="card" href="book-{b['id']}.html" data-title="{escape(b['title'].lower())}" data-author="{escape(b['author'].lower())}" data-genre="{escape(b['genre'])}">
<div class="cover" style="background:{b['color']}">{escape(b['title'])}</div>
<div class="info"><h3>{escape(b['title'])}</h3>
<div class="muted">{escape(b['author'])}</div>
<div class="muted">{stars(b['rating'])} {b['rating']}</div>
<div class="price">${b['price']:.2f}</div></div></a>"""

SEARCH_JS = """<script>
const q=document.getElementById('q'),g=document.getElementById('g');
function filter(){
  const t=q.value.toLowerCase(), genre=g.value;
  document.querySelectorAll('.card').forEach(c=>{
    const ok=(c.dataset.title.includes(t)||c.dataset.author.includes(t))&&(!genre||c.dataset.genre===genre);
    c.classList.toggle('hidden',!ok);
  });
}
q.addEventListener('input',filter); g.addEventListener('change',filter);
</script>"""

def build():
    books = json.loads((HERE / "books.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    (OUT / "style.css").write_text(CSS, encoding="utf-8")

    genres = sorted({b["genre"] for b in books})
    options = "".join(f'<option value="{escape(x)}">{escape(x)}</option>' for x in genres)
    home = f"""<h1>Find your next book</h1>
<div class="controls">
<input id="q" placeholder="Search by title or author...">
<select id="g"><option value="">All genres</option>{options}</select></div>
<div class="grid">{''.join(card(b) for b in books)}</div>"""
    (OUT / "index.html").write_text(page(SITE_NAME, home, SEARCH_JS), encoding="utf-8")

    for b in books:
        detail = f"""<p><a href="index.html">← Back to all books</a></p>
<div class="detail">
<div class="cover" style="background:{b['color']}">{escape(b['title'])}</div>
<h1>{escape(b['title'])}</h1>
<p class="muted">by {escape(b['author'])} · {escape(b['genre'])}</p>
<p>{stars(b['rating'])} {b['rating']} / 5</p>
<p>{escape(b['description'])}</p>
<p class="price">${b['price']:.2f}</p>
<a class="btn" href="#" onclick="alert('Added to cart (demo)');return false">Add to cart</a>
</div>"""
        (OUT / f"book-{b['id']}.html").write_text(page(b["title"], detail), encoding="utf-8")
    print(f"Built {len(books)} book pages in {OUT}")

if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        import functools, http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("Open http://localhost:8000  (Ctrl+C to stop)")
        http.server.ThreadingHTTPServer(("", 8000), handler).serve_forever()
