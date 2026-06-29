---
name: secret-scrub
description: Use before any git commit in this project — especially the very first commit of a new repository, or any commit touching .env files, config, credentials, or tokens. Scans staged changes for secrets before they enter git history, where they're extremely hard to fully remove afterward. Trigger this whenever about to run git commit, before staging files with git add ahead of a commit, or when initializing a new git repository in a folder that may already contain credential files.
---

# Secret scrub

A secret that reaches git history is much harder to undo than one that's caught before committing — even deleting the file later leaves it recoverable from history. The cost of checking first is a few seconds; the cost of not checking is a leaked credential that may need to be rotated and a history that may need rewriting.

**Why this matters:** in this project, a real live Discord bot token was found sitting in plaintext in multiple files — including a file literally named to be a safe placeholder template — before the repository was even initialized. Catching this before the first commit, rather than after, is the entire point of this skill.

## The check, before every commit

1. **Look for files that might carry credentials** before staging anything: anything named like `.env`, `*token*`, `*secret*`, `*credentials*`, or config files that commonly hold API keys. Don't assume a file is safe because of its name (a `.env.example` meant as a safe template can still have a real value pasted into it by mistake — check its actual contents, not just its name).

2. **Write (or update) `.gitignore` before the first `git add`**, covering every credential-bearing file identified above, plus the usual generated/runtime artifacts for the stack in use.

3. **After staging, scan the staged diff itself** — `git diff --cached` — for:
   - The specific secret value(s) already known to exist in the project, if any were found during step 1.
   - General secret-shaped patterns: long base64-ish/hex tokens, strings following `key=`, `token=`, `password=`, `secret=`, cloud-provider key prefixes (e.g. `AKIA` for AWS).

4. **Confirm `.gitignore` is actually doing its job** — `git check-ignore <file>` for each credential-bearing file found in step 1. A `.gitignore` entry that doesn't match (wrong path, wrong pattern) gives false confidence.

5. **Only commit once the scan is clean.** If something turns up: unstage it (`git restore --staged <file>`), fix `.gitignore` or scrub the value, then re-run the scan before trying again.

## If a secret already reached a previous commit

This skill is about prevention, not history rewriting — if a secret is found in already-committed history (not just staged), that's a separate, more careful operation (history rewriting affects anyone who's already cloned the repo) and should be flagged explicitly rather than handled as a routine fix.
