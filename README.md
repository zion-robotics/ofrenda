# Ofrenda

An offering for forgotten developers.

Ofrenda reads the history of any git project, finds the contributors who stopped showing up, and writes a short remembrance for each one with a small local model (Gemma 3 1B through Ollama). Everything runs on your own machine. Nothing is uploaded.

The names, dates and counts are printed by plain code. The model only writes two sentences per person, and a checker throws away any sentence that invents a number, date or file name.

## Quick start (3 steps)

1. Install [Python](https://www.python.org/downloads/), [Git](https://git-scm.com/downloads) and [Ollama](https://ollama.com/download).
2. Download the small model once: `ollama pull gemma3:1b`
3. Run it on a GitHub link or a folder:

```
python ofrenda.py https://github.com/octocat/Hello-World
```

That is all. There is nothing to pip install.

Not sure what to give it? Run `python ofrenda.py` with nothing after it and it will ask you for a folder or a link.

## On Windows without typing

Double-click `haunt.bat`. It asks for a project folder or GitHub link, runs Ofrenda, and opens the result as a web page. You can also drag a project folder onto `haunt.bat`.

## Make a gallery

Want one page that links to many hauntings? Put one GitHub link per line in `links.txt`, then run:

```
python make_gallery.py
```

On Windows you can double-click `make_gallery.bat` instead. It runs Ofrenda on every link, saves one page per project in a `gallery` folder, and builds `gallery/index.html` with a card for each. Upload the whole `gallery` folder to any free static host (GitHub Pages, Render, DigitalOcean) to share it.

Options: `--max 3` (ghosts per project), `--tone tribute`, `--title "My Gallery"`, `--source-url https://github.com/you/ofrenda`.

Each project can take a few minutes on a small laptop, so start it and let it run.

## Options

| Option | What it does |
| --- | --- |
| `--all` | Treat every contributor as a ghost (best for solo projects) |
| `--days 90` | Days of silence before someone counts as a ghost |
| `--max 5` | How many ghosts to write about |
| `--tone tribute` | Gentle remembrance (default). Use `spooky` for a ghost story |
| `--html FILE` | Also save a web page you can open or screenshot |
| `--model gemma3:1b` | Any model you have pulled in Ollama |
| `--temperature 0.6` | Higher is more creative, lower is calmer |
| `--alias "OLD=NEW"` | Merge two git names of one person (can be repeated) |
| `--no-type` | Print text instantly instead of the typing effect |
| `--no-ai` | Skip the model and use plain template text |

## Good projects to try

- Your own old projects (use `--all`, and you become the ghost)
- Any abandoned open-source project with many contributors
- A GitHub link, which is read once and then deleted from your computer

## Tips for a low-memory laptop

- Close your browser and heavy apps while it runs.
- The first ghost is slow because the model is loading. The rest are faster.
- Keep `--max` between 3 and 5.

## Troubleshooting

- "Could not reach Ollama": open the Ollama app or run `ollama serve`.
- "Model not found": run `ollama pull gemma3:1b`.
- "Could not read as a git project": the folder needs a `.git` folder inside. Use a GitHub link instead.
- No ghosts found: use `--all`, or lower `--days`.
- GitHub links need internet once to fetch the history. After that, the writing runs fully offline.
