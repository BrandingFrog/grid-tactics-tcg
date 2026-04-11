FROM mediawiki:1.43

# Install system deps (git needed by composer for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
      git unzip default-mysql-client ca-certificates curl \
  && rm -rf /var/lib/apt/lists/* \
  # apt upgrade of apache2 packages may enable mpm_event alongside mpm_prefork;
  # mediawiki:1.43 uses mpm_prefork (required for mod_php). Force it.
  && a2dismod mpm_event mpm_worker 2>/dev/null || true \
  && a2enmod mpm_prefork

# Install composer (phar) — mediawiki:1.43 does NOT ship composer
RUN curl -sSLo /usr/local/bin/composer https://getcomposer.org/download/latest-stable/composer.phar \
 && chmod +x /usr/local/bin/composer \
 && composer --version

WORKDIR /var/www/html

# mediawiki image ships /var/www/html owned by www-data; composer needs to write
# composer.json/composer.lock here. Temporarily loosen ownership for the build step.
RUN chown -R root:root /var/www/html

# Install Semantic MediaWiki via composer. mediawiki:1.43 ships with a
# pinned phpunit dev dep that has a security advisory blocking updates —
# use --update-no-dev so dev deps are never resolved, and --no-audit to
# suppress the advisory check entirely.
ENV COMPOSER_ALLOW_SUPERUSER=1
# Cache bust: 2026-04-09T17 — force rebuild for ParserFunctions
# mediawiki:1.43 ships composer.json with phpunit/phpunit 9.6.16 in require-dev,
# which composer's security audit rejects (PKSA-z3gr-8qht-p93v) even when we
# --update-no-dev. Strip phpunit from require-dev before calling composer require.
RUN php -r '$j = json_decode(file_get_contents("composer.json"), true); unset($j["require-dev"]["phpunit/phpunit"]); file_put_contents("composer.json", json_encode($j, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));' \
 && composer require --no-interaction --no-audit --update-no-dev \
      mediawiki/semantic-media-wiki "~5.0" \
 && composer dump-autoload --optimize --no-dev \
 && chown -R www-data:www-data /var/www/html

# Verify ParserFunctions is bundled (mediawiki:1.43 ships it in extensions/)
RUN test -f extensions/ParserFunctions/extension.json && echo "ParserFunctions OK" || (echo "ParserFunctions MISSING" && exit 1)

# Install Citizen skin via composer
RUN composer require --no-interaction --no-audit --update-no-dev \
      starcitizentools/citizen-skin \
 && composer dump-autoload --optimize --no-dev

# PHP OPcache tuning — cache compiled PHP bytecode in memory
RUN echo '\
opcache.enable=1\n\
opcache.memory_consumption=256\n\
opcache.interned_strings_buffer=16\n\
opcache.max_accelerated_files=10000\n\
opcache.revalidate_freq=60\n\
opcache.validate_timestamps=1\n\
' > /usr/local/etc/php/conf.d/opcache-tuning.ini

# Apache mpm_prefork tuning — limit workers for Railway container
RUN echo '\
<IfModule mpm_prefork_module>\n\
    StartServers           2\n\
    MinSpareServers        2\n\
    MaxSpareServers        5\n\
    MaxRequestWorkers      25\n\
    MaxConnectionsPerChild 1000\n\
</IfModule>\n\
' > /etc/apache2/conf-available/mpm-tuning.conf \
 && a2enconf mpm-tuning

# Stage our LocalSettings template (entrypoint copies it into place post-install)
COPY LocalSettings.php /tmp/LocalSettings.template.php
COPY docker-entrypoint-wiki.sh /usr/local/bin/docker-entrypoint-wiki.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-wiki.sh

# Healthcheck — Railway waits for this before routing traffic
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -sf http://localhost/api.php?action=query&meta=siteinfo&format=json || exit 1

EXPOSE 80
ENTRYPOINT ["docker-entrypoint-wiki.sh"]
CMD ["apache2-foreground"]
