#!/bin/sh
# Nightly backup of Compliance OS data (database + evidence files). Schedule with cron, e.g.:
#   30 1 * * * /opt/compliance-os/deploy/backup.sh
set -e
SRC=/var/lib/compliance-os
DST=/backup/compliance-os
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$DST"
sqlite3 "$SRC/cct.sqlite3" ".backup '$DST/cct-$STAMP.sqlite3'"
tar -czf "$DST/attachments-$STAMP.tar.gz" -C "$SRC" attachments
find "$DST" -type f -mtime +90 -delete
