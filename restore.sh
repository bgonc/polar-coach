#!/bin/bash
# Restore polar-coach data from Filen backup
set -euo pipefail

BACKUP_DIR="$HOME/Documents/Backups/polar-coach"
APP_DIR="$(dirname "$0")"

if [ ! -d "$BACKUP_DIR/data" ]; then
    echo "No backup found at $BACKUP_DIR"
    exit 1
fi

echo "Restoring from backup ($(cat "$BACKUP_DIR/last_backup.txt" 2>/dev/null || echo 'unknown date'))"

# Restore data
cp -r "$BACKUP_DIR/data" "$APP_DIR/"

# Restore .env if not present
if [ ! -f "$APP_DIR/.env" ] && [ -f "$BACKUP_DIR/.env" ]; then
    cp "$BACKUP_DIR/.env" "$APP_DIR/"
fi

echo "Restored successfully."
