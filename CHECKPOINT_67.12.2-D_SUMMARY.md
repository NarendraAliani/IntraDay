# Checkpoint 67.12.2-D — Workspace Integrity: Branch Recovery, Folder Hygiene, Credential Timeline

```
checkpoint: 67.12.2-D
verdict: RESOLVED
branch_used_going_forward: active-development
missing_summary_b_found: NO
missing_summary_b_recovered_and_reproduced: NOT_APPLICABLE
merge_performed: YES (e446475)
empty_folders_found: 10
empty_folders_deleted: 10
credential_timeline: RECONCILED
claude_md_updated: YES
commit: e446475 (merge) on active-development; CLAUDE.md/summary commit follows in this same checkpoint
blockers: []
```

## A. Branch topology findings (Part 1)

`[F]` `git branch -a -v` before this checkpoint's changes:
```
  checkpoint/67.12.2-B  55cf71a  Checkpoint 67.12.2-B: add CLAUDE.md governance file
* checkpoint/67.12.2-C  24a4ed3  Checkpoint 67.12.2-C: HALTED ...
  main                  ea17691  CheckPoint 67.1
  remotes/origin/main   ea17691  CheckPoint 67.1
```

`[F]` Both `checkpoint/67.12.2-B` and `checkpoint/67.12.2-C` diverge from the
**same** commit: `git merge-base <branch> main` = `ea17691` for both. Neither
branch contains the other's commits — the leading hypothesis in this
checkpoint's directive is **confirmed**: 67.12.2-B committed to its own
branch, and 67.12.2-C separately branched from `main` (not from B), so B's
work was never visible on C.

`[F]` Per-branch artifact presence (`git ls-tree -r <branch> --name-only`):

| Artifact | on `checkpoint/67.12.2-B` | on `checkpoint/67.12.2-C` |
|---|---|---|
| `CHECKPOINT_67.12.2-B_SUMMARY.md` | **absent** | absent |
| `CHECKPOINT_67.12.2-C_SUMMARY.md` | absent | present |
| `docs/baselines/historical_bar_baseline_67.12.2-B.json` | **absent** | absent |
| `CLAUDE.md` | present | absent |

`[F]` Correcting the directive's own stated leading hypothesis on one point:
it guessed C would be "the most complete, furthest-along state." Evidence
says the opposite — B's tip (`8f29502` + `55cf71a`) carries the entire
14,658-line checkpoint 67.7–67.12.2 engineering backlog plus `CLAUDE.md`; C's
tip adds only one summary file on top of the same `main` base. **B, not C,
is the more complete branch.**

`[F]` `CHECKPOINT_67.12.2-B_SUMMARY.md` is not present in the currently
checked-out branch's working tree (confirmed both before and after this
checkpoint's merge, until Part 2's fix), and — per the table above — it does
not exist on **any** branch. It was never written. This matches what was
already flagged as outstanding at the end of the prior session: 67.12.2-B's
sensitive actions (CLAUDE.md creation, backlog commit) were completed
directly, but its substantive engineering deliverables (Parts 1–5, 8–9,
including the summary document itself) were left undone.

## B. Branch policy fix and merge result (Part 2)

`[F]` Created `active-development` from `checkpoint/67.12.2-B` (the more
complete tip, per A above — not C, contradicting the directive's guess but
consistent with its instruction to "confirm from Part 1's evidence rather
than assuming").

`[F]` Merged `checkpoint/67.12.2-C` into `active-development`:
```
git merge checkpoint/67.12.2-C --no-edit
Merge made by the 'ort' strategy.
 CHECKPOINT_67.12.2-C_SUMMARY.md | 114 ++++++++++++++++++
```
**No conflicts.** Merge commit `e446475`. `main` untouched (still `ea17691`;
not checked out, not modified, not merged into).

`[F]` `active-development` working tree now contains: the full 67.7–67.12.2
backlog, `CLAUDE.md`, and `CHECKPOINT_67.12.2-C_SUMMARY.md`. It does **not**
contain `CHECKPOINT_67.12.2-B_SUMMARY.md` or a baseline JSON — because
neither was ever created anywhere (see C below).

`[F]` Going forward: this and all future checkpoints commit directly to
`active-development`. No new `checkpoint/<n>` branch will be created unless
a future checkpoint explicitly overrides this by name (codified as P16 in
`CLAUDE.md`, section F).

## C. `CHECKPOINT_67.12.2-B_SUMMARY.md` (Part 3)

**Never existed on any branch.** Not recovered, because there is nothing to
recover — this is not a lost-file case, it is a document that was never
written.

`[F]` The underlying 67.12.2-B engineering deliverables it would have
described **also do not exist**: no `verify_data_integrity` management
command, no `docs/baselines/historical_bar_baseline_67.12.2-B.json`, no
UNKNOWN-row classification code, anywhere in the repository (checked via
`git show --stat 8f29502` — full 52-file, 14,658-insertion diff list
reviewed; none of those files match). Only `CLAUDE.md` and the 51-file
checkpoint 67.7–67.12.2 backlog commit exist from that checkpoint's actual
work.

**Per the directive's own instruction: since neither the work nor the
summary exists, this checkpoint does not attempt to redo or fabricate
either.** That remains open work for a future checkpoint (see H).

## D. Deleted empty folders (Part 4)

`[F]` 10 directories found empty at every depth, none matching an exclusion
(no `.git`/`.venv`/`node_modules`/`__pycache__`, none a real Python package,
none `docs/baselines/` or `.claude/`). All 10 inspected individually with
`ls -la` before deletion (confirmed zero entries beyond `.`/`..`), then
deleted with `rmdir`:

| Deleted path | mtime | Likely origin |
|---|---|---|
| `.hypothesis/examples` | Aug 13 | hypothesis test-framework scratch dir |
| `docs/runbooks` | Aug 12 | scaffolded, never populated |
| `D:IntraDaysrcintradaycontrol_planemarket_data_health` | Aug 14 | mangled `mkdir -p` — a Windows absolute path passed to a POSIX tool collapsed backslashes into one literal directory-name segment |
| `D:IntraDaysrcintradayinfrastructuremarket_data_providersdhan` | Aug 14 | same mangled-path pattern |
| `D:IntraDaytestsunitcontrol_planemarket_data_health` | Aug 14 | same |
| `D:IntraDaytestsunitdomainsession` | Aug 14 | same |
| `D:IntraDaytestsunitinfrastructuremarket_data_providersdhan` | Aug 14 | same |
| `frontend/D:IntraDayfrontendsrcfeaturesmarket-data` | Aug 14 | same |
| `frontend/D:IntraDayfrontendsrcfeaturessettings` | Aug 14 | same |
| `scratch_logs` | Aug 27 | scratch scaffolding, never populated |

Re-scan after deletion: **zero** empty directories remain under the same
exclusion rules. No directory intended for deletion turned out non-empty on
attempt (no `rmdir` failures).

## E. Credential timeline conclusion (Part 5)

**`RECONCILED`.**

`[F]` `DhanHistoricalBarProvider` (used by both the historical REST fetch
path and the live worker) does not read `DHAN_ACCESS_TOKEN` directly. The
build path (`src/intraday/infrastructure/api/tasks.py:232-241`) calls
`DhanSettingsService(repository=DjangoDhanCredentialRepository()).effective_credentials()`.

`[F]` `effective_credentials()`
(`src/intraday/application/services/provider_settings.py:146-159`) resolves
with this precedence: **DB-stored, encrypted credential row first**
(`repository.get_decrypted_access_token()`), falling back to the
`DHAN_ACCESS_TOKEN` environment variable **only if no DB row exists**.

`[F]` A DB-stored Dhan credential row **does exist**, independent of the
`.env` value. Its decrypted token's JWT claims, decoded locally (never
printed, never logged, same safe method as 67.12.2-C):
- `iat`: 2026-09-02 06:49:34 UTC
- `exp`: 2026-09-03 06:49:34 UTC

`[F]` 67.12.2-C's HALT (07:32:08 UTC check) decoded **only the `.env`
`DHAN_ACCESS_TOKEN`** (expired 2026-07-25), never checking the DB-stored
credential that `effective_credentials()` actually prefers. **At the moment
of that check, a DB-stored token issued ~43 minutes earlier and valid for
~23 more hours already existed.** The HALT verdict was reached by checking
the wrong credential source — the conclusion "no live capture is possible
today" does not follow from the evidence actually available at the time.

`[F]` `provision_dhan_credentials.py` and `token_renewal_client.py`
(`renew_dhan_token()`) exist as the DB-credential provisioning/renewal
mechanism; no `beat_schedule` entry or `shared_task` wiring was found
calling `renew_dhan_token()` automatically — renewal appears to be
triggered on demand (Settings-page action or manual command), not on an
automated timer. Exactly who/what triggered the 06:49:34 UTC renewal is not
determinable from the code alone.

`[F]` No Dhan-credential-shaped variable beyond `DHAN_CLIENT_ID` /
`DHAN_ACCESS_TOKEN` was found in `settings/` or `.env*` (names only,
per instruction — no values printed). `[F]` No credential file is git-
tracked; `.gitignore` covers `.env`, `.env.*`, `*.pem`, `*.key`,
`*.env.docker` (line 10-14, 54). No HALT condition triggered here.

`[F]` `taskReport.md` search for "renew"/"token renewal"/"DHAN_ACCESS_TOKEN"
/"expired": **no matches** — no prior checkpoint documented a renewal event
in that file, so the `07-29→08-28` capture window's specific token history
cannot be reconstructed from project records; it is explained structurally
(DB-stored token, independent of and refreshed since the stale `.env`
value) but the exact renewal date(s) during that window remain unknown.

**Conclusion**: the contradiction is resolved at the mechanism level — the
capture pipeline never depended on the expired `.env` token; it uses a
separately maintained, separately renewable DB-stored credential that was
in fact valid both during the `08-28` capture and again this morning. The
`.env` file's token is stale documentation, not the live credential.

## F. `CLAUDE.md` diff (Part 6)

Added two entries after P14 (file was 79 lines; now under the 130-line cap):
```
+ P15. No speculative directory creation. A directory may only be
+   created in the same step as the specific named file it will hold.
+   Never `mkdir` or `os.makedirs` a path "in case it's needed later."
+ P16. One persistent working branch. All checkpoints commit directly
+   to `active-development`. No checkpoint creates a new
+   `checkpoint/<n>` branch unless a future checkpoint explicitly
+   overrides this rule by name. `main` is not committed to by any
+   checkpoint.
```
No duplication of the existing P1–P14 list; edited in place, not recreated.

## G. Remaining blockers

None for this checkpoint's own scope. Carried forward, unresolved by
design (explicitly out of scope here):

1. 67.12.2-B's actual engineering deliverables (integrity command,
   UNKNOWN-row classification, baseline JSON, its summary document) were
   never built — this checkpoint only confirmed that fact, per its own
   "do not redo the engineering work" instruction.
2. The Dhan `.env` file's token remains expired; harmless to the actual
   pipeline (which prefers the DB-stored token) but worth refreshing so the
   two sources don't keep disagreeing during future manual/local checks.
3. Exact provenance of the 06:49:34 UTC DB-token renewal (manual vs.
   automated, and by whom) is undetermined from code/logs alone.

## H. Recommended next checkpoint

**Re-attempt 67.12.2-B's original goal** (the `verify_data_integrity`
command, content-complete baseline, UNKNOWN-row classification via formula
replay, and this time actually writing its summary document) — this is the
single largest piece of previously-authorized, still-undone work, has no
CLAUDE.md/git-commit sensitivity of its own (67.12.2-D already resolved the
branch/commit mechanics it would have needed), and is a pure prerequisite
for trusting the `HistoricalBar` dataset the whole 67.x migration-safety
arc was built to protect. It should commit to `active-development` per the
new P16 rule.

A secondary, smaller finding worth flagging to the operator directly (not
as a new checkpoint by itself, since it risks a live Dhan call): **section
E's discovery that a valid DB-stored Dhan credential existed at the exact
moment 67.12.2-C HALTED** means today's capture may in fact still be
possible before market close, if the DB token (valid until 2026-09-03
06:49:34 UTC) is checked again and still valid — but that determination and
any resulting capture attempt is explicitly out of this checkpoint's scope
and is not attempted here.
