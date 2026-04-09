FROM mediawiki:1.42

# Install system deps (git needed by composer for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
      git unzip default-mysql-client \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /var/www/html

# Install Semantic MediaWiki via composer (composer ships in mediawiki image)
RUN composer require --no-update mediawiki/semantic-media-wiki "~4.1" \
 && composer update --no-dev --optimize-autoloader

# Stage our LocalSettings template (entrypoint copies it into place post-install)
COPY LocalSettings.php /tmp/LocalSettings.template.php
COPY docker-entrypoint-wiki.sh /usr/local/bin/docker-entrypoint-wiki.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-wiki.sh

EXPOSE 80
ENTRYPOINT ["docker-entrypoint-wiki.sh"]
CMD ["apache2-foreground"]
