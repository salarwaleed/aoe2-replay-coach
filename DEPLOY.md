# Deploying the bot to a free Oracle Cloud VM (24/7, $0)

This runs the **Discord bot** in the cloud so your PC is free. The heavy
**pipelines (Ollama synthesis) stay on your PC** — they can't run on free tiers;
run them on-demand and push the resulting profiles up to the VM's MinIO later.

What works after this guide: all text commands (`!eco`, `!build`, `!gg`,
`!coach`, `!civ`, `!counter`, `!match`, …) and TTS speaking. Profiles start
empty, so answers are ruleset-grounded but not yet player-personalised until
you populate MinIO (see the last section). **Voice input (`!listen`) is a
follow-up** — it needs the `davey` DAVE library built for ARM (see bottom).

---

## 1. Create the free Oracle VM (your part, ~15 min)

1. Sign up at **cloud.oracle.com** → "Start for free". A credit card is needed
   for identity verification only; Always Free resources are never charged.
2. Console → **Compute → Instances → Create instance**:
   - **Image**: Canonical Ubuntu 24.04
   - **Shape**: `VM.Standard.A1.Flex` (Ampere ARM) — set **1 OCPU / 6 GB**
     (well within the Always Free 4-OCPU/24-GB allowance; plenty for the bot).
     If ARM capacity is unavailable, retry, or use `VM.Standard.E2.1.Micro` (x86).
   - **SSH keys**: upload your public key (or let Oracle generate one and
     download the private key).
   - Leave networking default. **No inbound ports are needed** — the bot makes
     only outbound connections to Discord/Google. (SSH port 22 is open by default.)
3. Click **Create**, wait ~1 min, copy the instance's **public IP**.

## 2. Connect and install Docker

```bash
ssh ubuntu@<PUBLIC_IP>          # (or 'opc@' on some Oracle images)

sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER    # run docker without sudo
newgrp docker                    # apply the group now (or log out/in)
docker --version                 # confirm
```

## 3. Get the code onto the VM (private repo)

Authenticate GitHub on the VM, then clone:

```bash
# Install GitHub CLI and log in (browser device-code flow)
sudo apt-get install -y gh
gh auth login          # GitHub.com → HTTPS → Yes → device code

gh repo clone salarwaleed/aoe2-discord-coach
cd aoe2-discord-coach
```

## 4. Add secrets (never committed)

```bash
cp deploy/secrets.env.example deploy/secrets.env
nano deploy/secrets.env         # paste your DISCORD_TOKEN and OPENCLAW_API_KEY
```
Fill in `DISCORD_TOKEN` and `OPENCLAW_API_KEY` (the same values from your local
`.env`). Save (Ctrl+O, Enter, Ctrl+X).

## 5. Launch

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f bot
```
Watch for `✅ Teletron-1 ... is online and ready`. Then in Discord, try `!eco`.

**It's now running 24/7.** It survives reboots (`restart: unless-stopped`) and
your PC can be off. Manage it with:
```bash
docker compose -f deploy/docker-compose.yml ps       # status
docker compose -f deploy/docker-compose.yml restart bot
docker compose -f deploy/docker-compose.yml down      # stop everything
```

## 6. Update after code changes

```bash
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

---

## Populating player profiles (personalised answers)

Profiles are produced by the pipelines on your PC and stored in MinIO. To get
them onto the VM, either:

- **Point your PC's Pipeline 3 at the VM's MinIO**: temporarily expose the VM
  MinIO (add `"9000:9000"` to the minio service ports + an Oracle ingress rule),
  then run Pipeline 3 locally with `S3_ENDPOINT_URL=http://<VM_IP>:9000`. Remove
  the exposure afterwards.
- **Or copy the profile objects up** with `mc mirror` (MinIO client) from your
  local MinIO to the VM's.

Until then the bot answers generically (still Voobly-v1.6-grounded) — every
command degrades gracefully when a profile is missing.

## Voice input (`!listen`) — follow-up

The image installs `ffmpeg`/`libopus` so the bot can **speak**. Receiving and
transcribing voice additionally needs the `davey` DAVE E2EE library (see
`voice_listen.py`), which must be built for the VM's CPU architecture (ARM64 on
Ampere). That's a separate step — the bot runs fine without it; only `!listen`
is affected.
