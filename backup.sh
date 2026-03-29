#!/bin/bash
# Backup polar-coach data to Filen-synced folder
set -euo pipefail

BACKUP_DIR="$HOME/Documents/Backups/polar-coach"
DATA_DIR="$(dirname "$0")/data"
ENV_FILE="$(dirname "$0")/.env"

mkdir -p "$BACKUP_DIR"

# Copy data folder
if [ -d "$DATA_DIR" ]; then
    cp -r "$DATA_DIR" "$BACKUP_DIR/data"
fi

# Copy .env (API keys)
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$BACKUP_DIR/.env"
fi

# Timestamp
date > "$BACKUP_DIR/last_backup.txt"
echo "Backed up to $BACKUP_DIR"
