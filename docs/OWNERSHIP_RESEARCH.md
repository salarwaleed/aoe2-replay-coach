# Ownership research — attributing unit production in VER 9.F replays

*Research log, 2026-07-02/03. Status: ledger shipped (merged to main); TC-inference
pending one labeled 2-human game.*

## The problem

QUEUE/MULTIQUEUE commands (unit production) carry **no player id** in the legacy
Voobly VER 9.F format. Without attribution, profiles can't say *who* built an army.
Full game-state simulation (Option C) was rejected: replays contain only inputs, so
recovering battle events would require a deterministic engine re-implementation
(OpenAge-scale work) with silent-corruption risk.

## What shipped: the ownership ledger (in `pipeline/replay_parser.py`)

Commands that carry BOTH `player_id` and `object_ids` (ORDER, MOVE, FORMATION,
WALL, DELETE) create claims `object_id → player`. QUEUE/MULTIQUEUE payloads carry
the **producing building's** object id — if all of an event's building ids resolve
to one player, the event is attributed (`extras.attributed_via="ownership_ledger"`).
Conflicting claims discard the object entirely (never guess).

**Verified**: labeled game (delete-TC signing) attributes 4/4 villagers to the
correct player; regression-clean (non-queue events byte-identical); zero false
attributions observed anywhere.

## Corpus survey (26 readable files, 2026-07-03)

- Overall coverage: **1,970 / 22,170 queue events = 8.9%** (median file 1.5%,
  max 42% — small 2-player games attribute far better than big team games).
  Early 3-file sampling suggested 18–22%; that sample was unrepresentative.
- Claim volume: 122,867 claims; MOVE produces the most claims but **100% of
  successful building attributions come via ORDER** (MOVE claims land on units).
- Conflicts are real but rare (6 corpus-wide): objects legitimately changing
  hands mid-game (likely Monk conversions). Discard rule is correct.

## Discoveries

### Action id 176 — undocumented Voobly ownership assertion
11-byte command, layout `<3x, H object_id, 2x, B player_id, 3x>`. Appears ~8×
per corpus; **100% agreement with the ledger** in every checkable case. Too rare
to add coverage; useful as a free correctness cross-check. Not yet wired in.

### Starting-TC id pattern (the coverage doubler — PENDING PROOF)
In ~70% of multi-player files, the starting TCs' object ids form a tight cluster
spaced in exact **multiples of 10** (e.g. `6067, 6077, 6087, …` for 8 players).
Base offset is file-local (map-generation counter; no cross-file pattern).
Labeled evidence so far: slot 1 (SalarWaleed) held the cluster base in both
labeled games (TC 4116, then 4115). Early villager production dominates queue
volume, so attributing starting TCs would roughly **double effective coverage**.

**Open question**: does sorted-id order map to player slot order? Needs ONE game
with 2+ humans where each human queues villagers and **deletes their own TC
before resigning** (DELETE signs the TC with their player id). AI games can
never answer this — see below.

### AI actions are not recorded
Replays store only **human** inputs; AI behavior is simulated from scripts and
never appears in the command stream. AI TCs/production are invisible to any
command-level analysis. All labeled testing must use human players.

### Rejected: rally-point adjacency
GATHER_POINT (no player id) cross-referenced by shared object id adds ~0.15%;
the `target_id` variant contradicts known ownership 47% of the time (enemy
buildings being attacked). Do not implement.

## How to sign a building in-game (for labeled tests)

Box-select only picks units — buildings can't be drag-selected with units. The
reliable signing action: **select the building alone and press Delete** (DELETE
carries player_id + object_ids). In a throwaway game, delete the TC right before
resigning; the whole-match ledger retroactively attributes everything it produced.

## Reproducibility

Survey scripts + per-file JSON: `docs/ownership_survey/` (copied from the
session scratchpad). Ground-truth files: `rec.20260630-115805.mgz` (TC 4116),
`rec.20260703-000219.mgz` (TC 4115, delete-signed, 4/4 attributed).

## Next steps

1. One 2+ human game with delete-TC signing → prove/disprove slot mapping.
2. If proven: implement first-TC attribution in `replay_parser.py` (detect
   multiples-of-10 cluster among earliest-queued buildings, map sorted ids to
   slots), gated on the clean-cluster check (~70% of files).
3. Optionally wire action-176 as an extra claim source / validator.
