# IntraDay User Guide

This directory contains the **Dynamic Digital Tutorial Guide** —
Checkpoint 25's standalone, interactive onboarding guide for
installing, starting, and safely operating the IntraDay local
application.

## Opening the guide

Double-click [`index.html`](index.html) to open it directly in your
browser — no server, no build step, and no internet connection
required. It also works if you're browsing this repository's rendered
Markdown and click through from [README.md](../../README.md).

## What's here

```
docs/user-guide/
    index.html      — the guide itself (all content lives here)
    css/style.css    — styling (light/dark, responsive, print-friendly)
    js/main.js       — navigation, client-side search, progress tracking
    validate.py       — lightweight structural/security validation (no
                         external dependencies) - also runs as part of
                         the normal `pytest` suite via
                         tests/unit/documentation/test_user_guide.py
```

No `assets/` directory exists yet — no screenshots were captured for
this checkpoint (see "Screen-by-Screen Guide" in the tutorial itself);
it uses text/table descriptions instead, explicitly marked as
illustrative rather than real screenshots. Create `assets/` if a
future checkpoint adds real images/diagrams.

## Audience

Written to be understandable by three overlapping audiences without
needing three separate documents: a software developer, a technically
comfortable user, and a complete layman. The "I Know Nothing — Start
Here" section exists specifically for the third group; the "Developer
Mode" section links out to the project's full architecture
documentation for the first, without duplicating it here.

## Keeping this guide honest

Every claim in this guide is derived directly from the repository's
actual code and configuration at the time it was written — not a
generic template. If a feature doesn't exist yet, the guide says so
explicitly (`NOT IMPLEMENTED` / `DEFERRED`), rather than describing
aspirational behavior. If you find something in this guide that no
longer matches the running application, please update both together —
`validate.py` catches broken links and leaked secrets, but it cannot
catch a claim that has become factually stale.

## Validation

```bash
poetry run python docs/user-guide/validate.py
```

Checks: every local CSS/JS asset reference resolves to a real file,
every internal `#section` link points at a real section, no
JWT-shaped or other credential-shaped strings appear anywhere in the
guide, and no leftover unfinished-work markers remain. Also runs as
part of `poetry run pytest`.
