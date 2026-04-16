#!/bin/bash
set -e
cd /var/www/html

# Force single MPM — apt-get install in the build layer can enable mpm_event
# alongside mediawiki:1.42's mpm_prefork. Apache refuses to start with both.
a2dismod -f mpm_event 2>/dev/null || true
a2dismod -f mpm_worker 2>/dev/null || true
a2enmod mpm_prefork 2>/dev/null || true

DB_HOST="${MW_DB_SERVER%%:*}"
DB_PORT="${MW_DB_SERVER#*:}"
if [ "$DB_PORT" = "$MW_DB_SERVER" ]; then DB_PORT=3306; fi

echo "[entrypoint] Waiting for MySQL at ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if php -r "try { new PDO('mysql:host=${DB_HOST};port=${DB_PORT};dbname=${MW_DB_NAME}', '${MW_DB_USER}', '${MW_DB_PASS}'); echo 'ok'; } catch(Exception \$e) { exit(1); }" 2>/dev/null | grep -q ok; then
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
REQ_TABLES="user ipblocks site_stats page revision"
SCHEMA_OK=1
for t in $REQ_TABLES; do
  exists=$(php -r "
    try {
      \$pdo = new PDO('mysql:host=${DB_HOST};port=${DB_PORT};dbname=information_schema', '${MW_DB_USER}', '${MW_DB_PASS}');
      \$stmt = \$pdo->query(\"SELECT COUNT(*) FROM tables WHERE table_schema='${MW_DB_NAME}' AND table_name='${t}'\");
      echo \$stmt->fetchColumn();
    } catch(Exception \$e) { echo '0'; }
  " 2>/dev/null || echo 0)
  if [ "${exists:-0}" = "0" ]; then
    echo "[entrypoint] required table '${t}' missing — schema incomplete"
    SCHEMA_OK=0
    break
  fi
done

if [ "$SCHEMA_OK" = "0" ]; then
  echo "[entrypoint] Dropping any stale tables in ${MW_DB_NAME} before install..."
  php -r "
    \$pdo = new PDO('mysql:host=${DB_HOST};port=${DB_PORT};dbname=${MW_DB_NAME}', '${MW_DB_USER}', '${MW_DB_PASS}');
    \$pdo->exec('SET FOREIGN_KEY_CHECKS=0');
    \$tables = \$pdo->query(\"SELECT table_name FROM information_schema.tables WHERE table_schema='${MW_DB_NAME}'\")->fetchAll(PDO::FETCH_COLUMN);
    foreach (\$tables as \$t) { \$pdo->exec('DROP TABLE IF EXISTS \`' . \$t . '\`'); }
    \$pdo->exec('SET FOREIGN_KEY_CHECKS=1');
    echo 'dropped ' . count(\$tables) . ' tables';
  " 2>/dev/null || true
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

# Ensure MediaWiki upload directories exist and are writable by www-data.
# Railway's ephemeral filesystem drops these on restart, causing upload stash
# failures ("Could not store file at mwstore://local-backend/local-temp/...").
mkdir -p /var/www/html/images/{temp,thumb,archive,deleted,lockdir}
chown -R www-data:www-data /var/www/html/images
chmod -R 775 /var/www/html/images

echo "[entrypoint] images/ disk usage:"
df -h /var/www/html/images
echo "[entrypoint] top 20 space-eaters in images/:"
du -sh /var/www/html/images/* 2>/dev/null | sort -rh | head -20
echo "[entrypoint] thumb dir size (if present):"
du -sh /var/www/html/images/thumb 2>/dev/null || echo "  (no thumb dir)"
echo "[entrypoint] temp dir size:"
du -sh /var/www/html/images/temp 2>/dev/null || echo "  (no temp dir)"

# Run update.php every boot — idempotent, handles SMW schema bring-up and upgrades
echo "[entrypoint] Running update.php..."
php maintenance/update.php --quick || {
  echo "[entrypoint] update.php FAILED — continuing anyway so logs are visible"
}

echo "[entrypoint] Handing off to: $@"
exec "$@"
