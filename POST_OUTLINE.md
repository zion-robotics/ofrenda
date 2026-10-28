# DEV post outline

The write-up carries the most weight, so use the DEV "Ghost in the Machine" submission template and fill it with this structure. Write it in your own voice.

## 1. Opening moment
Start with the moment that surprised you: the first time Gemma wrote a line about a real commit that made you pause. Quote it. Keep notes while you test so you have this ready.

## 2. What I built
Two or three sentences. Ofrenda reads a project's git history, finds the developers who left, and writes a remembrance for each one with a local model. Say who it is for.

## 3. How I read the theme
Ghost in the Machine as both halves: the spooky side (abandoned code still has a presence) and the Día de los Muertos side (remembering the people who built things before you).

## 4. Demo
Screen recording of a run on your own old project, plus a screenshot of the HTML page. Show the terminal text appearing slowly.

## 5. How it works
- Plain code reads `git log` and decides who counts as a ghost
- Plain code writes the names, dates and numbers
- Gemma 3 1B (through Ollama) writes only the short paragraph
- Why: a 1B model gets facts wrong, so the program never lets it write them

Mention that you designed around the model's weakness. Judges like honesty about limits.

## 6. Why open innovation mattered
Use your real situation:
- It runs on a 4GB laptop with a 1B open-weight model
- It works with the internet off
- A project's history stays on your machine
- It does not depend on a service that can shut down or change its pricing

## 7. What I would do next
One or two honest ideas, such as reading issue threads or supporting more models.

## Categories to enter
- Best Use of Gemma
- Best Use of a .tech Domain (only if you really host the demo page on one)
- Any other category you genuinely used while building

## Before you submit
- Demo runs with no errors in the recording
- Repo link works and the README is clear
- Post submitted well before October 31, 11:59 PM PDT
