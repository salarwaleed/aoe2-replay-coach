---
name: verify-finding
description: Use whenever a subagent, an external source, or your own quick read of code reports a "finding" that later work will depend on — an extracted data table, a measured value, a claimed root cause, a "ground truth," or data copied from one place into another. Before trusting it or building further work on top of it, independently verify it. Trigger this especially when copying a lookup table or constant out of existing code into something new, when a single agent's self-report is the only evidence for something important, or when a person flags that a result "feels wrong" even without proof.
---

# Verify finding

A finding is not verified just because it was reported, copied, or returned by a confident-sounding agent. It is verified once it has been checked against something independent of how it was first produced.

**Why this matters:** in this project, a civilization-id lookup table was copied verbatim from existing code into a new pipeline and taken at face value. It was wrong — alphabetically ordered rather than the game's real internal id order — and it shipped silently into production data until a person noticed something felt off ("I don't think I played that civilization recently"). The bug wasn't in the extraction logic; it was in trusting an inherited table without checking it. This skill exists to catch that whole class of bug before it ships, not after a human happens to notice.

## The check

1. **Name the specific claim.** Not "the parser works" — the precise value, table, or assertion that other work will depend on (e.g. "id 9 maps to civilization X").
2. **Find an independent way to check it.** Independent means it doesn't share the same blind spot as the original method. Options, roughly in order of cheapness:
   - A different ground-truth source that's already known-correct (e.g. a file format that *can* be read by an existing, trusted parser, even if it's not the main data source).
   - A cheap structural sanity check (does the value fall in a plausible range, are there bytes/data nearby that should independently confirm it, were any guards/asserts violated).
   - A second agent, given the same raw input but no knowledge of the first agent's method or output, asked to derive the same answer from scratch.
3. **Actually perform the check** — don't just assert that a check "could" be done.
4. **Compare and report honestly.** State match, mismatch, or partial match plainly. A "close enough" result that doesn't fully match is a finding that needs more work, not a pass.
5. **Don't build on top of an unverified or contradicted finding.** If the check turns up a discrepancy, stop and investigate before letting downstream work (a merge, a pipeline re-run, a profile generation) proceed on top of it.

## A cheap pattern worth reusing

When something was extracted from a format that's hard to parse (a reverse-engineered binary layout, an undocumented API, a scraped page), look for a *related but easier* case that a trusted, existing tool already handles correctly — then run your new extraction logic against that easier case too and diff the two outputs. If they agree, that's real evidence your method is sound, not just plausible-looking. This is often free: it reuses data and tools that already exist, with no new infrastructure.
