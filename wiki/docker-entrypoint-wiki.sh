#!/bin/bash
set -e
cd /var/www/html

DB_HOST="${MW_DB_SERVER%%:*}"
DB_PORT="${MW_DB_SERVER#*:}"
if [ "$DB_PORT" = "$MW_DB_SERVER" ]; then DB_PORT=3306; fi

echo "[entrypoint] Waiting for MySQL at ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MW_DB_USER" -p"$MW_DB_PASS" -e "SELECT 1" "$MW_DB_NAME" >/dev/null 2>&1; then
    echo "[entrypoint] MySQL is up."
    break
  fi
  echo "[entrypoint]   ...retry $i"
  sleep 2
done

# Detect whether MediaWiki schema is present and complete. Check for several
# core tables — previous Taqasta attempts may have left a half-installed DB
# (e.g. 'user' present but 'ipblocks' missing). If any required table is
# missing, wipe the DB and run install.php fresh.
MYSQL_FLAGS=(-h "$DB_HOST" -P "$DB_PORT" -u "$MW_DB_USER" -p"$MW_DB_PASS")
REQ_TABLES="user ipblocks site_stats page revision"
SCHEMA_OK=1
for t in $REQ_TABLES; do
  exists=$(mysql "${MYSQL_FLAGS[@]}" -N -B -e \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${MW_DB_NAME}' AND table_name='${t}';" 2>/dev/null || echo 0)
  if [ "${exists:-0}" = "0" ]; then
    echo "[entrypoint] required table '${t}' missing — schema incomplete"
    SCHEMA_OK=0
    break
  fi
done

if [ "$SCHEMA_OK" = "0" ]; then
  echo "[entrypoint] Dropping any stale tables in ${MW_DB_NAME} before install..."
  mysql "${MYSQL_FLAGS[@]}" -N -B -e \
    "SELECT CONCAT('DROP TABLE IF EXISTS \`', table_name, '\`;') FROM information_schema.tables WHERE table_schema='${MW_DB_NAME}';" \
    "$MW_DB_NAME" 2>/dev/null | \
    (echo "SET FOREIGN_KEY_CHECKS=0;"; cat; echo "SET FOREIGN_KEY_CHECKS=1;") | \
    mysql "${MYSQL_FLAGS[@]}" "$MW_DB_NAME" || true
  echo "[entrypoint] MediaWiki not installed — running install.php..."
  php maintenance/install.php \
    --dbtype=mysql \
    --dbserver="${DB_HOST}:${DB_PORT}" \
    --dbname="$MW_DB_NAME" \
    --dbuser="$MW_DB_USER" \
    --dbpass="$MW_DB_PASS" \
    --installdbuser="$MW_DB_USER" \
    --installdbpass="$MW_DB_PASS" \
    --server="$MW_SITE_SERVER" \
    --scriptpath="" \
    --lang=en \
    --pass="$MW_ADMIN_PASS" \
    --confpath=/tmp/mw-install-out \
    "${MW_SITE_NAME:-Grid Tactics Wiki}" "${MW_ADMIN_USER:-Admin}"
  echo "[entrypoint] install.php complete."
fi

# Always install our LocalSettings (overrides whatever install.php generated)
cp /tmp/LocalSettings.template.php /var/www/html/LocalSettings.php
chown www-data:www-data /var/www/html/LocalSettings.php

# Run update.php every boot — idempotent, handles SMW schema bring-up and upgrades
echo "[entrypoint] Running update.php..."
php maintenance/update.php --quick || {
  echo "[entrypoint] update.php FAILED — continuing anyway so logs are visible"
}

echo "[entrypoint] Handing off to: $@"
exec "$@"
