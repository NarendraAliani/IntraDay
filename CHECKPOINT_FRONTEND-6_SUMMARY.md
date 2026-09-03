# Checkpoint FRONTEND-6 — Make the Glyph Guarantee Durable

## Part 1 — expanded coverage

`theme.quality.test.ts`'s existing glyph-guard test
(`"the shell, dashboard and shared status components use no Unicode
glyph icons"`) only checked a fixed 6-file list
(`ICONOGRAPHY_GATED_FILES`) — its own comment (lines 138-145) honestly
named "individual feature pages still contain their own inline
Unicode markers; migrating ~40 further files was judged a larger,
riskier change... recorded as a Remaining Gap."

Added a **new, separate test** (kept alongside the original rather than
replacing it, so both the narrow original guarantee and the new broad
one are independently visible in test output):
`"every feature-page file uses no Unicode glyph icons, except Reports'
two known-deferred labels"`. It reuses the file's own existing
`collectSourceFiles()` walker (already used by the emoji-check test),
scoped to `src/features/` — every `.tsx` file under every feature
folder, not a hand-maintained list — with the same banned-glyph
character class (`[●○◐✕✖✓✔⚠⚙]`) the original test already used.

**Exemption, scoped to exact line content, not the whole file**:

```ts
const KNOWN_DEFERRED_GLYPH_LINES = new Set<string>([
  '  SATISFIED: "✓ Satisfied",',
  '  BLOCKED: "⊘ Blocked",',
]);
```

Only these two exact lines in `ReportsOverviewPage.tsx` are exempted —
the ones checked-in as CHECKPOINT_FRONTEND-2 through -5's own,
explicitly-tracked, deliberately-deferred exception. Any *other* line
in that same file, or any change to these two lines' content, still
fails the test. This deliberately does **not** exempt the whole file,
per the checkpoint's own instruction — a future glyph regression
anywhere else in `ReportsOverviewPage.tsx` will still be caught.

## What the wider run actually found

**One real hit on the first run — my own explanatory comment**, not a
UI glyph: `ReportsOverviewPage.tsx:20`'s FRONTEND-5 comment quoted the
removed `✕` character in prose ("used a raw `\"✕\"` Unicode glyph"),
which the character-class regex correctly flagged since it scans every
line, comments included. This is a genuinely different kind of hit
than what the guard exists to catch (a comment describing history, not
a component rendering a glyph as a status indicator) — the correct fix
was rewording the comment to avoid embedding the literal character
("cross mark" instead of `"✕"`), not adding a comment-line exemption
(which would create a laxer, harder-to-reason-about exemption
category for future checkpoints to abuse). Applied; re-ran; the test
now passes.

**After that one wording fix: zero further violations found anywhere
in `src/features/`.** This is the real, evidenced answer to the
question this checkpoint was built to settle: **FRONTEND-2 through
FRONTEND-5 already found and fixed every real informal status glyph
that existed** — nothing new surfaced. The ~40-file gap named back in
the original 64.80-F2-era comment was a real, honestly-documented risk
at the time, but this checkpoint's wider automated sweep confirms it
never materialized into an actual missed instance, at least not one
using this glyph set.

## Part 2 — re-verification

- `npm run build`: clean.
- `npm run typecheck`: clean.
- `npm test -- --run`: **361/361 passed** (360 prior + 1 new test),
  34/34 files, zero regressions.

## What this closes, and what stays open

This makes the glyph-icon-consistency guarantee **durable, not just
audited-once**: any future feature-page code that reintroduces a raw
status glyph (or any of the four+ checkpoints' worth of manual sweeps
missed) will now fail `npm test` automatically, rather than requiring
another manual grep pass. Reports' own two known glyphs, and its
broader density/layout question, remain exactly where every prior
checkpoint in this thread left them — untouched, deliberately deferred,
now additionally protected against silently growing into a third or
fourth undocumented exception.
