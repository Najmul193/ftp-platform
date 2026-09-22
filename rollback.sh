#!/usr/bin/env bash
# Roll the database back to a saved restore point.
#
#   ./rollback.sh              roll back to the most recent restore point
#   ./rollback.sh --list       show the restore points available
#   ./rollback.sh <stamp>      roll back to a specific one
#   ./rollback.sh --save       take a new restore point without rolling back
#
# This replaces the whole database. It does not touch your code; each restore
# point also has a matching git tag (restore-point-<stamp>) if you want the
# code that went with it:  git checkout restore-point-<stamp>

set -euo pipefail
cd "$(dirname "$0")"

DIR="var/backups"
CONTAINER="${FTP_DB_CONTAINER:-ftp-postgres}"
DB="${FTP_DB_NAME:-ftp}"
USER="${FTP_DB_USER:-ftp}"
PASS="${FTP_DB_PASSWORD:-ftp_dev}"

say() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok()  { printf '    \033[32mok\033[0m  %s\n' "$1"; }
die() { printf '    \033[31mxx\033[0m  %s\n' "$1" >&2; exit 1; }

mkdir -p "$DIR"

list() {
  say "Restore points"
  local found=0
  for f in "$DIR"/restore-point-*.dump; do
    [ -e "$f" ] || continue
    found=1
    printf '    %-22s %6s   %s\n' \
      "$(basename "$f" .dump | sed 's/^restore-point-//')" \
      "$(du -h "$f" | cut -f1)" \
      "$(date -r "$f" '+%d %b %Y %H:%M')"
  done
  [ "$found" = 1 ] || printf '    (none yet — run ./rollback.sh --save)\n'
}

save() {
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  docker exec -e PGPASSWORD="$PASS" "$CONTAINER" \
    pg_dump -U "$USER" -d "$DB" -Fc > "$DIR/restore-point-${stamp}.dump" \
    || die "could not reach the database in container '$CONTAINER'"
  echo "$stamp" > "$DIR/.latest-stamp"
  git tag -f "restore-point-${stamp}" -m "restore point" >/dev/null 2>&1 || true
  ok "saved $DIR/restore-point-${stamp}.dump (git tag restore-point-${stamp})"
}

case "${1:-}" in
  --list|-l) list; exit 0 ;;
  --save|-s) say "Saving a restore point"; save; exit 0 ;;
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
esac

STAMP="${1:-}"
[ -n "$STAMP" ] || STAMP="$(cat "$DIR/.latest-stamp" 2>/dev/null || true)"
[ -n "$STAMP" ] || { list; die "no restore point given and none recorded"; }

DUMP="$DIR/restore-point-${STAMP}.dump"
[ -f "$DUMP" ] || { list; die "no such restore point: $STAMP"; }

say "Rolling back to $STAMP"
printf '    \033[31mThis replaces the entire database with that snapshot.\033[0m\n'
printf '    Anything loaded since then is discarded.\n'
read -r -p "    Type the stamp to confirm ($STAMP): " reply
[ "$reply" = "$STAMP" ] || die "cancelled"

# Take a safety copy first: rolling back is itself a destructive act, and the
# state being replaced may be the one someone actually wanted.
say "Safety copy of the current state"
save

say "Restoring"
docker exec -i -e PGPASSWORD="$PASS" "$CONTAINER" \
  pg_restore -U "$USER" -d "$DB" --clean --if-exists --no-owner < "$DUMP" \
  2>&1 | grep -vE "^pg_restore: (dropping|creating|processing|implied)" || true

ROWS=$(docker exec -e PGPASSWORD="$PASS" "$CONTAINER" \
  psql -U "$USER" -d "$DB" -tAc "SELECT count(*) FROM ftp_calculation_results" 2>/dev/null || echo "?")
ok "restored — $ROWS calculated rows"

echo
printf '\033[32mRolled back to %s.\033[0m\n' "$STAMP"
printf '  Matching code:  git checkout restore-point-%s\n' "$STAMP"
printf '  Restart:        ./stop.sh && ./start.sh\n'
