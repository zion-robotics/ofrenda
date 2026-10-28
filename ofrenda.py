#!/usr/bin/env python3
"""
Ofrenda: an offering for forgotten developers.

Reads the git history of any project, finds the contributors who stopped
showing up, and asks a small local model (Gemma through Ollama) to write a
short remembrance for each one. All facts (names, dates, counts) come from
plain code. The model only writes the prose, so it cannot invent the facts.

Everything runs offline on your own machine. Standard library only.
"""
import argparse
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timezone

SEP = "@@OFRENDA@@"

# Make ANSI colors work in the Windows console and keep unicode output safe.
os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USE_COLOR = sys.stdout.isatty()


def paint(text, code):
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def gold(t):
    return paint(t, "38;5;214")


def pale(t):
    return paint(t, "38;5;252")


def dim(t):
    return paint(t, "2")


# ---------------------------------------------------------------- git side

def run_git(repo, *args):
    try:
        result = subprocess.run(
            ["git", "-C", repo, "-c", "core.quotepath=false", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        sys.exit("Git is not installed or not on your PATH. Install Git first.")
    if result.returncode != 0:
        msg = result.stderr.strip() or "git command failed"
        sys.exit(f"Could not read '{repo}' as a git project.\n{msg}")
    return result.stdout


def read_history(repo):
    """Return commits newest first: name, timestamp, subject, files."""
    out = run_git(repo, "log", f"--pretty=format:{SEP}%an|%at|%s", "--name-only")
    commits = []
    cur = None
    for line in out.splitlines():
        if line.startswith(SEP):
            parts = line[len(SEP):].split("|", 2)
            if len(parts) < 3:
                cur = None
                continue
            name, ts, subject = parts
            try:
                ts = int(ts)
            except ValueError:
                cur = None
                continue
            cur = {
                "name": name.strip() or "Unknown",
                "ts": ts,
                "subject": subject.strip(),
                "files": [],
            }
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur["files"].append(line.strip())
    return commits


BOT_NAMES = {"lovable", "github", "github actions"}


def is_bot(name):
    low = name.lower()
    return "[bot]" in low or low in BOT_NAMES or re.search(r"\bbot\b", low) is not None


def group_people(commits):
    people = {}
    for c in commits:
        if is_bot(c["name"]):
            continue
        key = c["name"].lower()
        p = people.get(key)
        if p is None:
            p = {
                "key": key,
                "name": c["name"],
                "count": 0,
                "first_ts": c["ts"],
                "first_msg": c["subject"],
                "last_ts": c["ts"],
                "last_msg": c["subject"],
                "msgs": [],
                "files": Counter(),
            }
            people[key] = p
        p["count"] += 1
        if c["ts"] <= p["first_ts"]:
            p["first_ts"], p["first_msg"] = c["ts"], c["subject"]
        if c["ts"] >= p["last_ts"]:
            p["last_ts"], p["last_msg"] = c["ts"], c["subject"]
        if c["subject"] and c["subject"] not in p["msgs"] and len(p["msgs"]) < 6:
            p["msgs"].append(c["subject"])
        p["files"].update(c["files"])
    return people


def find_cursed_files(repo, commits, ghost_keys, limit=5):
    """Files that still exist, whose last toucher is a ghost. Oldest first."""
    tracked = set(run_git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
    last_touch = {}
    for c in commits:  # newest first
        for f in c["files"]:
            ts = last_touch.get(f, (None, 0))[1]
            if f not in last_touch or c["ts"] > ts:
                last_touch[f] = (c["name"], c["ts"])
    cursed = [
        (f, name, ts)
        for f, (name, ts) in last_touch.items()
        if f in tracked and name.lower() in ghost_keys
    ]
    cursed.sort(key=lambda x: x[2])
    return cursed[:limit]


# -------------------------------------------------------------- time helpers

def fmt_date(ts):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{dt:%B} {dt.day}, {dt.year}"


def ago(ts, now):
    days = int((now - ts) // 86400)
    if days < 1:
        return "today"
    if days < 60:
        return f"{days} days ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


# ------------------------------------------------------------------ the AI

TONES = {
    "tribute": {
        "voice": (
            "You are writing a short remembrance for a developer who left a software "
            "project, like a note placed beside a candle on an ofrenda. Speak directly "
            "to the developer, using their first name and the word 'you'. Be warm and "
            "a little eerie."
        ),
        "example_facts": (
            "- First name: Maya\n"
            "- Last commit message: \"fix typo in forecast\" (6 years ago)\n"
            "- File they worked on most: forecast.js"
        ),
        "example": (
            "Maya, your last words were \"fix typo in forecast\", and forecast.js has "
            "waited for you ever since. Tonight someone lit a candle in the empty "
            "rooms of your code."
        ),
    },
    "spooky": {
        "voice": (
            "You are the ghost of a developer who left a software project. Speak in "
            "the first person as the ghost, haunting the file you once worked on. "
            "Be eerie with a little dark humor."
        ),
        "example_facts": (
            "- First name: Maya\n"
            "- Last commit message: \"fix typo in forecast\" (6 years ago)\n"
            "- File they worked on most: forecast.js"
        ),
        "example": (
            "I am Maya, and I still drift through forecast.js, whispering "
            "\"fix typo in forecast\" to no one. The rain never arrives, because "
            "I never finished writing it."
        ),
    },
}


def fact_lines(p, now):
    first_name = p["name"].split()[0]
    lines = [
        f"- First name: {first_name}",
        f"- Last commit message: \"{p['last_msg']}\" ({ago(p['last_ts'], now)})",
    ]
    top = [os.path.basename(f) for f, _ in p["files"].most_common(1)]
    if top:
        lines.append(f"- File they worked on most: {top[0]}")
    return "\n".join(lines)


def make_prompt(p, now, tone):
    t = TONES[tone]
    return (
        f"{t['voice']}\n\n"
        "RULES: Write exactly 2 sentences. Use only the facts given. "
        "Quote the last commit message word for word. Mention the file by name. "
        "Do not mention any number or date. Do not invent events. Do not use "
        "dashes, bullet points, headings or asterisks. Avoid the words quiet, "
        "presence, journey, tapestry, subtle, gentle, testament and landscape. "
        "Start directly, with no intro.\n\n"
        f"EXAMPLE FACTS:\n{t['example_facts']}\n\n"
        f"EXAMPLE OUTPUT:\n{t['example']}\n\n"
        "Now write a new one for the facts below. Do not copy the example.\n\n"
        f"FACTS:\n{fact_lines(p, now)}\n\n"
        "OUTPUT:\n"
    )


NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"hundred|thousand|twice)\b", re.I)
BANNED = re.compile(
    r"\b(testament|tapestry|journey|landscape|subtle|gentle|presence|digital)\b", re.I)
FILE_LIKE = re.compile(r"\b[\w\-]+\.[A-Za-z]{1,5}\b")


def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


QUOTE_RE = re.compile(r'[\u201c"](.+?)[\u201d"]\)?')


def repair_quotes(sentence, messages):
    """Make every quoted phrase match a real commit message.
    Returns None if the sentence quotes something that was never written."""
    ok = [True]

    def repl(m):
        seg = m.group(1).strip()
        n = _norm(seg)
        for msg in messages:
            nm = _norm(msg)
            if not n or not nm:
                continue
            if SequenceMatcher(None, n, nm).ratio() >= 0.85:
                return "\u201c" + msg + "\u201d"
            if len(n) >= 6 and n in nm:
                return "\u201c" + seg + "\u201d"
        ok[0] = False
        return m.group(0)

    fixed = QUOTE_RE.sub(repl, sentence)
    return fixed if ok[0] else None


def validate_text(text, facts, quotes=()):
    """Keep only sentences that do not invent numbers, dates, file names or quotes."""
    facts_low = facts.lower()
    facts_digits = set(re.findall(r"\d+", facts))
    kept = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not s:
            continue
        s = repair_quotes(s, quotes) if quotes else s
        if s is None:
            continue
        if BANNED.search(s):
            continue
        if any(d not in facts_digits for d in re.findall(r"\d+", s)):
            continue
        if any(w.lower() not in facts_low for w in NUMBER_WORDS.findall(s)):
            continue
        if any(f.lower() not in facts_low for f in FILE_LIKE.findall(s)):
            continue
        kept.append(s)
    return " ".join(kept[:3])


def stream_ollama(prompt, model, host, temperature, on_token):
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": 2048,
                "num_predict": 170,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    parts = []
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                chunk = json.loads(raw)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                tok = chunk.get("response", "")
                if tok:
                    parts.append(tok)
                    on_token(tok)
                if chunk.get("done"):
                    break
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                f"Model '{model}' was not found. Run: ollama pull {model}"
            )
        raise RuntimeError(f"Ollama returned an error (HTTP {e.code}).")
    except urllib.error.URLError:
        raise RuntimeError(
            "Could not reach Ollama. Open the Ollama app (or run 'ollama serve') "
            "and try again."
        )
    return "".join(parts)


def clean_text(text):
    text = text.replace("*", "")
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"\s*[\u2013\u2014]\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(okay|ok|sure|here)[^.:]*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s+,", ",", text)
    return text.strip().strip('"').strip()


def typewrite(text, instant=False):
    if instant or not sys.stdout.isatty():
        print(pale(text))
        return
    sys.stdout.write("\033[38;5;252m")
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.12 if ch in ".!?" else 0.012)
    sys.stdout.write("\033[0m\n")


def fallback_text(p, now):
    return (
        f"{p['name']} left {p['count']} commit{'s' if p['count'] != 1 else ''} "
        f"behind. The last one, {ago(p['last_ts'], now)}, said: "
        f"\"{p['last_msg']}\". The code still remembers."
    )


# -------------------------------------------------------------- html report

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ofrenda for %%REPO%%</title>
<style>
  :root { --bg:#0d0b10; --card:#171320; --stone:#2a2433; --text:#e8e2d6; --muted:#9b93a6; --gold:#f2a33a; --marigold:#ff8c1a; --alive:#5fb3a8; }
  * { box-sizing: border-box; }
  body { margin:0; background:radial-gradient(ellipse at top, #1b1526 0%, var(--bg) 60%); color:var(--text);
         font-family: Georgia, 'Times New Roman', serif; line-height:1.65; }
  .petals { height:14px; background:
      radial-gradient(circle at 10px 7px, var(--marigold) 5px, transparent 6px) 0 0/28px 14px repeat-x,
      radial-gradient(circle at 24px 7px, #ffc247 4px, transparent 5px) 0 0/28px 14px repeat-x; opacity:.85; }
  main { max-width:820px; margin:0 auto; padding:44px 20px 80px; }
  h1 { color:var(--gold); font-weight:normal; letter-spacing:.06em; margin:0 0 6px; font-size:2rem; }
  .sub { color:var(--muted); margin:0 0 24px; }
  .score { display:inline-block; border:1px solid var(--gold); color:var(--gold); padding:6px 14px; border-radius:999px; font-size:.95rem; }
  .flame { display:inline-block; width:9px; height:15px; margin-right:8px; vertical-align:-1px;
           background:radial-gradient(ellipse at 50% 70%, #fff3b0 0%, #ffb02e 45%, #ff6a00 80%, transparent 100%);
           border-radius:50% 50% 50% 50% / 65% 65% 35% 35%; animation:flicker 1.8s infinite alternate; box-shadow:0 0 12px 3px rgba(255,150,30,.45); }
  @keyframes flicker { 0%{opacity:.7; transform:scale(.92) rotate(-3deg);} 50%{opacity:1;} 100%{opacity:.85; transform:scale(1.08) rotate(3deg);} }
  .ghost { display:flex; gap:22px; margin:34px 0; align-items:flex-start; }
  .stone { flex:0 0 210px; background:linear-gradient(#332b3f, var(--stone)); border:1px solid #3d3549;
           border-radius:105px 105px 8px 8px; padding:34px 18px 22px; text-align:center; box-shadow:0 0 26px rgba(255,140,26,.08); }
  .stone h2 { margin:6px 0 2px; color:var(--gold); font-weight:normal; font-size:1.15rem; line-height:1.3; }
  .years { margin:0 0 12px; color:var(--muted); font-size:.85rem; letter-spacing:.12em; }
  .epitaph { margin:0; font-style:italic; font-size:.92rem; color:var(--text); }
  .words { flex:1; background:var(--card); border-left:3px solid var(--marigold); border-radius:6px; padding:18px 22px; }
  .meta { color:var(--muted); font-size:.85rem; margin:0 0 10px; }
  .story { margin:0; }
  h3 { color:var(--gold); font-weight:normal; margin-top:50px; }
  ul { padding-left:20px; color:var(--muted); }
  .row { display:flex; align-items:center; gap:12px; margin:6px 0; font-size:.88rem; }
  .who { flex:0 0 150px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .track { position:relative; flex:1; height:12px; background:#1a1522; border-radius:6px; }
  .bar { position:absolute; top:0; height:12px; border-radius:6px; }
  .bar.gone { background:linear-gradient(90deg, #7a4a12, var(--marigold)); }
  .bar.here { background:var(--alive); }
  .axis { display:flex; justify-content:space-between; margin:4px 0 0 162px; color:var(--muted); font-size:.78rem; }
  .legend { color:var(--muted); font-size:.82rem; margin-top:10px; }
  footer { margin-top:50px; color:var(--muted); font-size:.85rem; }
  @media (max-width:640px) { .ghost { flex-direction:column; align-items:stretch; } .stone { flex-basis:auto; } .who { flex-basis:90px; } .axis { margin-left:102px; } }
</style>
</head>
<body>
<div class="petals"></div>
<main>
  <h1><span class="flame"></span>Ofrenda for %%REPO%%</h1>
  <p class="sub">An offering for the developers this project no longer hears from.</p>
  <p><span class="score">%%SUMMARY%%</span></p>
%%CARDS%%
%%TIMELINE%%
%%CURSED%%
  <footer>Facts come from the git history. Words written by %%MODEL%%, running offline on one laptop.</footer>
</main>
<div class="petals"></div>
</body>
</html>
"""


def timeline_html(people, ghost_keys, now):
    top = sorted(people, key=lambda p: p["count"], reverse=True)[:12]
    if not top:
        return ""
    top.sort(key=lambda p: p["first_ts"])
    start = min(p["first_ts"] for p in top)
    span = max(now - start, 1)
    rows = []
    for p in top:
        left = (p["first_ts"] - start) / span * 100
        width = max((p["last_ts"] - p["first_ts"]) / span * 100, 1.2)
        width = min(width, 100 - left)
        cls = "gone" if p["key"] in ghost_keys else "here"
        rows.append(
            f'  <div class="row"><span class="who">{html.escape(p["name"])}</span>'
            f'<div class="track"><div class="bar {cls}" '
            f'style="left:{left:.1f}%;width:{width:.1f}%"></div></div></div>'
        )
    start_year = datetime.fromtimestamp(start, tz=timezone.utc).year
    return (
        "  <h3>Who stayed, and who left</h3>\n"
        + "\n".join(rows)
        + f'\n  <div class="axis"><span>{start_year}</span><span>today</span></div>\n'
        + '  <p class="legend">Orange: has gone quiet. Green: still around.</p>'
    )


def build_html(repo_name, summary, entries, cursed, now, model, people=None, ghost_keys=None):
    cards = []
    for p, text in entries:
        y1 = datetime.fromtimestamp(p["first_ts"], tz=timezone.utc).year
        y2 = datetime.fromtimestamp(p["last_ts"], tz=timezone.utc).year
        years = f"{y1}" if y1 == y2 else f"{y1} to {y2}"
        cards.append(
            '  <section class="ghost">\n'
            '    <div class="stone">\n'
            '      <span class="flame"></span>\n'
            f"      <h2>{html.escape(p['name'])}</h2>\n"
            f'      <p class="years">{years}</p>\n'
            f'      <p class="epitaph">&ldquo;{html.escape(p["last_msg"])}&rdquo;</p>\n'
            "    </div>\n"
            '    <div class="words">\n'
            f'      <p class="meta">{html.escape(fmt_date(p["first_ts"]))} to '
            f'{html.escape(fmt_date(p["last_ts"]))} &middot; {p["count"]} commit'
            f'{"s" if p["count"] != 1 else ""} &middot; last seen '
            f'{html.escape(ago(p["last_ts"], now))}</p>\n'
            f'      <p class="story">{html.escape(text)}</p>\n'
            "    </div>\n"
            "  </section>"
        )
    cursed_html = ""
    if cursed:
        items = "\n".join(
            f"    <li>{html.escape(f)}, last touched by {html.escape(n)} "
            f"({html.escape(ago(ts, now))})</li>"
            for f, n, ts in cursed
        )
        cursed_html = f"  <h3>Cursed files</h3>\n  <ul>\n{items}\n  </ul>"
    page = HTML_TEMPLATE
    for token, value in {
        "%%REPO%%": html.escape(repo_name),
        "%%SUMMARY%%": html.escape(summary),
        "%%CARDS%%": "\n".join(cards),
        "%%TIMELINE%%": timeline_html(people or [], ghost_keys or set(), now),
        "%%CURSED%%": cursed_html,
        "%%MODEL%%": html.escape(model),
    }.items():
        page = page.replace(token, value)
    return page


def is_url(text):
    return bool(re.match(r"^(https?://|git@)", text))


def _force_remove(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def clone_repo(url):
    """Clone just the history (no file contents) into a temp folder."""
    tmp = tempfile.mkdtemp(prefix="ofrenda_")
    print(dim("  Fetching the project history (one time, needs internet)..."))
    for extra in (["--filter=blob:none"], []):
        res = subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", *extra, url, tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if res.returncode == 0:
            break
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
    else:
        shutil.rmtree(tmp, onerror=_force_remove)
        sys.exit(f"Could not clone {url}\n{res.stderr.strip()}")
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return tmp, name or "project"


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Remember the developers a project forgot."
    )
    ap.add_argument("repo", nargs="?", default=None,
                    help="project folder or GitHub link (asks if left out)")
    ap.add_argument("--days", type=int, default=90,
                    help="days of silence before someone counts as a ghost (default 90)")
    ap.add_argument("--max", type=int, default=5, dest="max_ghosts",
                    help="how many ghosts to write about (default 5)")
    ap.add_argument("--all", action="store_true",
                    help="treat every contributor as a ghost")
    ap.add_argument("--tone", choices=sorted(TONES), default="tribute")
    ap.add_argument("--model", default="gemma3:1b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--html", metavar="FILE", help="also save an HTML report")
    ap.add_argument("--alias", action="append", default=[], metavar="OLD=NEW",
                    help="merge two names of one person, e.g. --alias \"zion-robotics=Zion Adeogun\"")
    ap.add_argument("--no-type", action="store_true",
                    help="print text instantly instead of the typing effect")
    ap.add_argument("--no-ai", action="store_true",
                    help="skip the model and use plain template text (good for testing)")
    args = ap.parse_args()

    target = args.repo
    if not target:
        try:
            target = input("  Paste a project folder or a GitHub link: ").strip().strip('"')
        except EOFError:
            target = ""
        if not target:
            sys.exit("No project given.")

    cleanup = None
    if is_url(target):
        repo, repo_name = clone_repo(target)
        cleanup = repo
    else:
        repo = os.path.abspath(target)
        repo_name = os.path.basename(repo.rstrip("\\/")) or repo

    try:
        run(args, repo, repo_name)
    finally:
        if cleanup:
            shutil.rmtree(cleanup, onerror=_force_remove)


def run(args, repo, repo_name):
    now = int(time.time())

    commits = read_history(repo)
    if not commits:
        sys.exit("This project has no commits yet.")
    aliases = {}
    for a in args.alias:
        if "=" in a:
            old_name, new_name = a.split("=", 1)
            aliases[old_name.strip().lower()] = new_name.strip()
    if aliases:
        for c in commits:
            c["name"] = aliases.get(c["name"].lower(), c["name"])
    people = group_people(commits)
    if not people:
        sys.exit("Only bots have committed to this project, so there is nobody to remember.")

    threshold = 0 if args.all else args.days * 86400
    ghosts_all = [p for p in people.values() if now - p["last_ts"] >= threshold]
    ghosts_all.sort(key=lambda p: (-p["count"], p["last_ts"]))  # biggest contributors first
    ghost_keys = {p["key"] for p in ghosts_all}
    ghosts = ghosts_all[: args.max_ghosts]

    total = len(people)
    pct = round(100 * len(ghosts_all) / total)
    summary = f"{len(ghosts_all)} of {total} contributors have gone quiet. Haunting level {pct}%"

    print()
    print(gold(f"  OFRENDA for {repo_name}"))
    print(dim(f"  {summary}"))
    print()

    if not ghosts:
        print(pale("  No ghosts here. Everyone is still around."))
        print(dim("  Try --days 30, or --all to remember everyone."))
        return

    entries = []
    for i, p in enumerate(ghosts, 1):
        print(gold(f"  ~ Ghost {i}: {p['name']}"))
        print(dim(f"    {fmt_date(p['first_ts'])} to {fmt_date(p['last_ts'])}"
                  f" | {p['count']} commit{'s' if p['count'] != 1 else ''}"
                  f" | last seen {ago(p['last_ts'], now)}"))
        print(dim(f"    Last words: \"{p['last_msg']}\""))
        print()
        if args.no_ai:
            text = fallback_text(p, now)
        else:
            if i == 1:
                print(dim("    (waking the spirits, the first one can take a moment...)"))
            counter = {"n": 0}
            sys.stdout.write("    summoning")
            sys.stdout.flush()

            def on_token(tok):
                counter["n"] += 1
                if counter["n"] % 6 == 0:
                    sys.stdout.write(".")
                    sys.stdout.flush()

            text = ""
            for attempt in range(3):
                try:
                    raw = stream_ollama(
                        make_prompt(p, now, args.tone),
                        args.model, args.host, args.temperature, on_token,
                    )
                except RuntimeError as e:
                    sys.exit(f"\n\n  {e}")
                text = validate_text(clean_text(raw), fact_lines(p, now),
                                         [p["last_msg"]])
                if text:
                    break
            sys.stdout.write("\r" + " " * 70 + "\r")
            text = text or fallback_text(p, now)
        typewrite(
            textwrap.fill(text, width=74, initial_indent="    ", subsequent_indent="    "),
            args.no_type,
        )
        print()
        entries.append((p, text))

    cursed = find_cursed_files(repo, commits, ghost_keys)
    if cursed:
        print(gold("  Cursed files (still here, last touched by someone who left)"))
        for f, name, ts in cursed:
            print(pale(f"    {f}") + dim(f"  | {name}, {ago(ts, now)}"))
        print()

    if args.html:
        page = build_html(repo_name, summary, entries, cursed, now,
                          "plain templates" if args.no_ai else args.model,
                          list(people.values()), ghost_keys)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(page)
        print(pale(f"  Saved the HTML offering to {args.html}"))
        print()


if __name__ == "__main__":
    main()
