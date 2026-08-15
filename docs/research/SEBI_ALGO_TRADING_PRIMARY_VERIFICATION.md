# SEBI Algo-Trading Framework — Primary Source Verification (Checkpoint 38 Part 2)

Follow-up to Checkpoint 37's `SIGNAL_COMMUNICATION_AND_COMPLIANCE_RESEARCH.md`,
which classified the SEBI algo-trading framework finding as
`VERIFIED_SECONDARY` and required primary verification before it could
be treated as an architectural assumption.

## What was verified this checkpoint

**`VERIFIED_PRIMARY`** (fetched directly from `sebi.gov.in`): the
circular exists, with an exact identity — **Circular No.
SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, "Safer participation of
retail investors in Algorithmic trading," dated 2025-02-04**, published
at `sebi.gov.in/legal/circulars/feb-2025/...`. A direct `WebFetch` of
that URL returned only the page's header/metadata (title, circular
number, date) — the full circular body did not render through the
fetch tool (likely a linked PDF or JS-rendered document viewer), so the
SPECIFIC technical provisions below remain secondary-sourced.

Also newly confirmed (`VERIFIED_PRIMARY` via a `sebi.gov.in` search
result listing, corroborating and refining Checkpoint 37's finding):
**the original effective date was pushed back by at least two
subsequent SEBI circulars** — an April 2025 "Extension of timeline for
formulation of implementation standards" and a September 2025
"Extension of timeline for implementation" circular both exist on
`sebi.gov.in` (titles and dates confirmed via search; full text not
fetched). This means Checkpoint 37's "mandatory since 2026-04-01"
framing may be **imprecise on the exact date** — multiple extensions
occurred, and the true final compliance milestone needs the actual
circular text to pin down exactly, not a secondary blog's summary.

## What remains `VERIFIED_SECONDARY / PRIMARY_CONFIRMATION_PENDING`

The SPECIFIC technical requirements Checkpoint 37 found (Algo-ID
tagging every order, broker-side per-algorithm exchange permission,
static IP, 2FA/OAuth, daily auto-logout) are corroborated by a search-
result snippet of the primary circular's own summary ("algo orders
will be tagged with a unique identifier to establish an audit trail...
brokers can provide algo trading facility to retail investors only
after obtaining requisite permission from stock exchanges for each
algorithm") — this is closer to primary than Checkpoint 37's
industry-blog sourcing, but still not the full circular text fetched
and read directly. **Per this checkpoint's explicit instruction, this
fact stays marked `VERIFIED_SECONDARY / PRIMARY_CONFIRMATION_PENDING`
until the full circular PDF is actually retrieved and read** — it is
not promoted to `VERIFIED_PRIMARY` on the strength of a search snippet
alone, applying the exact same "never silently promote" discipline
this project already applies to `SAMPLE_BAR` → `TRADING_GRADE_BAR`.

## What this means for IntraDay, unchanged from Checkpoint 37

Nothing here changes Checkpoint 37's conclusion: this project has no
Algo-ID/registration concept anywhere, does not place real orders, and
therefore is not currently non-compliant with anything — the framework
only binds a system that actually places algo-tagged orders with a
broker. It remains a **named, tracked P0 blocker for any future LIVE
trading checkpoint**, now with a stronger (partially primary-confirmed)
evidence base, still explicitly not fully verified.

## Recommended next verification step (not attempted this checkpoint)

Download the actual PDF from `sebi.gov.in/sebi_data/attachdocs/...`
(the direct attachment path, not the HTML landing page) and read the
full circular text — this checkpoint's `WebFetch` tool could not
render it, so this requires either a different fetch approach or the
user manually supplying the extracted text in a future checkpoint.
