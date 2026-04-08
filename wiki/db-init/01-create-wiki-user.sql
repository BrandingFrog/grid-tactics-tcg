-- Grid Tactics Wiki — pre-create the MediaWiki DB user with host wildcard.
--
-- Why: MediaWiki's CLI installer (maintenance/install.php) issues
--   GRANT ALL PRIVILEGES ON `wiki`.* TO 'wiki'@'<mediawiki-hostname>'
-- where <mediawiki-hostname> is the Docker container hostname (e.g. 'db' or
-- the container id). The matching CREATE USER statement, however, is issued
-- with host 'localhost', so the GRANT targets a user that does not exist and
-- the installer aborts.
--
-- Creating the user here with host '%' (any host) lets the installer's GRANT
-- succeed against an existing row. Docker network isolation still restricts
-- who can reach the DB.

CREATE DATABASE IF NOT EXISTS `wiki` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'wiki'@'%' IDENTIFIED BY 'wikipass';
GRANT ALL PRIVILEGES ON `wiki`.* TO 'wiki'@'%';
FLUSH PRIVILEGES;
