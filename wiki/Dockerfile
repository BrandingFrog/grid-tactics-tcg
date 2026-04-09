FROM mediawiki:1.42

# Install system deps (git needed by composer for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
      git unzip default-mysql-client ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Install composer (phar) — mediawiki:1.42 does NOT ship composer
RUN curl -sSLo /usr/local/bin/composer https://getcomposer.org/download/latest-stable/composer.phar \
 && chmod +x /usr/local/bin/composer \
 && composer --version

WORKDIR /var/www/html

# mediawiki image ships /var/www/html owned by www-data; composer needs to write
# composer.json/composer.lock here. Temporarily loosen ownership for the build step.
RUN chown -R root:root /var/www/html

# Install Semantic MediaWiki via composer
RUN composer require --no-update mediawiki/semantic-media-wiki "~4.1" \
 && COMPOSER_ALLOW_SUPERUSER=1 composer update --no-dev --optimize-autoloader \
 && chown -R www-data:www-data /var/www/html

# Stage our LocalSettings template (entrypoint copies it into place post-install)
COPY LocalSettings.php /tmp/LocalSettings.template.php
COPY docker-entrypoint-wiki.sh /usr/local/bin/docker-entrypoint-wiki.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-wiki.sh

EXPOSE 80
ENTRYPOINT ["docker-entrypoint-wiki.sh"]
CMD ["apache2-foreground"]
