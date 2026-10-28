#!/usr/bin/env python3
"""
Build a clickable gallery from a list of projects.

Put one GitHub link (or folder path) per line in links.txt, then run:

    python make_gallery.py

It runs Ofrenda on each project, saves one page per project, and writes an
index.html that links them all. Upload the whole gallery folder to any free
static host (GitHub Pages, Render, DigitalOcean) to share it.
"""
import argparse
import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
  :root { --bg:#0d0b10; --card:#171320; --text:#e8e2d6; --muted:#9b93a6; --gold:#f2a33a; --marigold:#ff8c1a; }
  * { box-sizing: border-box; }
  body { margin:0; background:radial-gradient(ellipse at top, #1b1526 0%, var(--bg) 60%); color:var(--text);
         font-family: Georgia, 'Times New Roman', serif; line-height:1.65; }
  .petals { height:14px; background:
      radial-gradient(circle at 10px 7px, var(--marigold) 5px, transparent 6px) 0 0/28px 14px repeat-x,
      radial-gradient(circle at 24px 7px, #ffc247 4px, transparent 5px) 0 0/28px 14px repeat-x; opacity:.85; }
  main { max-width:900px; margin:0 auto; padding:44px 20px 80px; }
  h1 { color:var(--gold); font-weight:normal; letter-spacing:.06em; margin:0 0 6px; font-size:2.1rem; }
  .sub { color:var(--muted); margin:0 0 34px; max-width:640px; }
  .flame { display:inline-block; width:9px; height:15px; margin-right:8px; vertical-align:-1px;
           background:radial-gradient(ellipse at 50% 70%, #fff3b0 0%, #ffb02e 45%, #ff6a00 80%, transparent 100%);
           border-radius:50% 50% 50% 50% / 65% 65% 35% 35%; animation:flicker 1.8s infinite alternate; box-shadow:0 0 12px 3px rgba(255,150,30,.45); }
  @keyframes flicker { 0%{opacity:.7; transform:scale(.92) rotate(-3deg);} 50%{opacity:1;} 100%{opacity:.85; transform:scale(1.08) rotate(3deg);} }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(380px, 1fr)); gap:22px; }
  a.card { display:block; text-decoration:none; color:inherit; background:var(--card); border:1px solid #2b2437;
           border-left:3px solid var(--marigold); border-radius:8px; padding:20px 22px; transition:transform .15s, box-shadow .15s; }
  a.card:hover { transform:translateY(-3px); box-shadow:0 0 24px rgba(255,140,26,.18); }
  a.card h2 { margin:0 0 8px; color:var(--gold); font-weight:normal; font-size:1.25rem; word-break:break-word; }
  .score { display:inline-block; border:1px solid var(--gold); color:var(--gold); padding:2px 10px; border-radius:999px; font-size:.78rem; }
  .who { margin:14px 0 2px; color:var(--gold); }
  .epitaph { margin:0 0 10px; font-style:italic; color:var(--muted); font-size:.92rem; }
  .story { margin:0 0 14px; font-size:.95rem; }
  .open { color:var(--marigold); font-size:.88rem; }
  footer { margin-top:50px; color:var(--muted); font-size:.85rem; }
  footer a { color:var(--gold); }
</style>
</head>
<body>
<div class="petals"></div>
<main>
  <h1><span class="flame"></span>%%TITLE%%</h1>
  <p class="sub">Remembrances for the developers these open-source projects no longer hear from. Facts come from public git history. The words were written offline by %%MODEL%% on one small laptop.</p>
  <div class="grid">
%%CARDS%%
  </div>
  <footer>%%SOURCE%%</footer>
</main>
<div class="petals"></div>
</body>
</html>
"""


def slugify(target, taken):
    name = target.rstrip("/\\").split("/")[-1].split("\\")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "project"
    base, n = slug, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def parse_page(path):
    s = open(path, encoding="utf-8").read()

    def grab(pattern, text=s):
        m = re.search(pattern, text, re.S)
        return m.group(1) if m else ""

    section = grab(r'<section class="ghost">(.*?)</section>')
    return {
        "repo": grab(r"<title>Ofrenda for (.*?)</title>"),
        "score": grab(r'<span class="score">(.*?)</span>'),
        "name": grab(r"<h2>(.*?)</h2>", section),
        "epitaph": grab(r'<p class="epitaph">(.*?)</p>', section),
        "story": grab(r'<p class="story">(.*?)</p>', section),
    }


def main():
    ap = argparse.ArgumentParser(description="Build a gallery of Ofrenda pages.")
    ap.add_argument("links", nargs="?", default="links.txt",
                    help="text file with one GitHub link or folder per line")
    ap.add_argument("--out", default="gallery", help="output folder (default: gallery)")
    ap.add_argument("--max", type=int, default=3, dest="max_ghosts",
                    help="ghosts per project (default 3)")
    ap.add_argument("--tone", default="tribute", choices=["tribute", "spooky"])
    ap.add_argument("--model", default="gemma3:1b")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--title", default="Ofrenda Gallery")
    ap.add_argument("--source-url", default="",
                    help="link to the Ofrenda code, shown in the footer")
    args = ap.parse_args()

    if not os.path.isfile(args.links):
        sys.exit(f"Could not find {args.links}. Create it with one GitHub link per line.")
    with open(args.links, encoding="utf-8") as fh:
        targets = [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    if not targets:
        sys.exit(f"{args.links} has no projects in it yet.")

    os.makedirs(args.out, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    taken, cards = set(), []

    for i, target in enumerate(targets, 1):
        slug = slugify(target, taken)
        page = os.path.join(args.out, slug + ".html")
        print(f"\n=== [{i}/{len(targets)}] {target}")
        if os.path.exists(page):
            os.remove(page)
        cmd = [sys.executable, os.path.join(HERE, "ofrenda.py"), target,
               "--max", str(args.max_ghosts), "--tone", args.tone,
               "--model", args.model, "--days", str(args.days),
               "--html", page, "--no-type"]
        if args.all:
            cmd.append("--all")
        if args.no_ai:
            cmd.append("--no-ai")
        res = subprocess.run(cmd, env=env)
        if res.returncode != 0 or not os.path.exists(page):
            print(f"    Skipped {target} (error, or no ghosts found).")
            continue
        info = parse_page(page)
        cards.append(
            f'    <a class="card" href="{slug}.html">\n'
            f"      <h2>{info['repo']}</h2>\n"
            f'      <span class="score">{info["score"]}</span>\n'
            f'      <p class="who">{info["name"]}</p>\n'
            f'      <p class="epitaph">{info["epitaph"]}</p>\n'
            f'      <p class="story">{info["story"]}</p>\n'
            '      <span class="open">Open the full offering &rarr;</span>\n'
            "    </a>"
        )

    if not cards:
        sys.exit("\nNo pages were made, so there is no gallery yet.")

    source = ""
    if args.source_url:
        source = f'Made with <a href="{html.escape(args.source_url)}">Ofrenda</a>.'
    index = INDEX_TEMPLATE
    for token, value in {
        "%%TITLE%%": html.escape(args.title),
        "%%MODEL%%": "plain templates" if args.no_ai else html.escape(args.model),
        "%%CARDS%%": "\n".join(cards),
        "%%SOURCE%%": source,
    }.items():
        index = index.replace(token, value)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(index)
    print(f"\nDone. {len(cards)} project(s) in the gallery.")
    print(f"Open {os.path.join(args.out, 'index.html')} in your browser.")


if __name__ == "__main__":
    main()
