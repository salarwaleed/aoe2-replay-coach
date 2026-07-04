# Discord bot image — multi-arch (works on Oracle Ampere ARM64 and x86).
FROM python:3.13-slim

# System deps:
#   ffmpeg    — TTS playback (!coach/!trainer speak)
#   libopus0  — Discord voice codec (send + receive)
#   libsodium23 — PyNaCl voice encryption
#   gcc       — in case any wheel needs a source build on ARM
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libopus0 libsodium23 gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching. The bot's requirements.txt plus
# three libs imported by the code but not pinned there:
#   requests    — cloud_llm (Gemini HTTP)
#   boto3       — pipeline.s3_store (profile reads from MinIO/S3)
#   audioop-lts — voice_listen imports stdlib `audioop`, removed in Py3.13
COPY ["age of empire discord bot/requirements.txt", "./bot-requirements.txt"]
RUN pip install --no-cache-dir -r bot-requirements.txt \
        requests boto3 audioop-lts

# App code: the bot package + the pipeline package it imports (s3_store, config).
COPY ["age of empire discord bot/", "./age of empire discord bot/"]
COPY ["pipeline/", "./pipeline/"]

# `pipeline` is a sibling package the bot imports — make the repo root importable.
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

WORKDIR "/app/age of empire discord bot"

# Secrets (DISCORD_TOKEN, OPENCLAW_*) come from the container environment
# (compose env_file), NOT baked into the image.
CMD ["python", "bot.py"]
