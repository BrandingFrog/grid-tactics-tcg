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

# Detect whether MediaWiki tables exist in the target DB
TABLES_EXIST=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MW_DB_USER" -p"$MW_DB_PASS" -N -B -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${MW_DB_NAME}' AND table_name='user';" 2>/dev/null || echo 0)

if [ "${TABLES_EXIST:-0}" = "0" ]; then
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
