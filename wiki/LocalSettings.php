<?php
# Grid Tactics Wiki — LocalSettings.php
# Reads all secrets/config from environment (Railway env vars).
if ( !defined( 'MEDIAWIKI' ) ) {
    exit;
}

# MediaWiki install path — required for wfLoadExtension/wfLoadSkin
$IP = getenv('MW_INSTALL_PATH') ?: '/var/www/html';

$wgSitename = getenv('MW_SITE_NAME') ?: 'Grid Tactics Wiki';
$wgMetaNamespace = 'Grid_Tactics_Wiki';

$wgServer = getenv('MW_SITE_SERVER') ?: 'http://localhost';
$wgScriptPath = '';
$wgArticlePath = '/wiki/$1';
$wgUsePathInfo = true;
$wgScriptExtension = '.php';

$wgEnableUploads = true;
$wgFileExtensions = [ 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg' ];

# Database — MW_DB_SERVER is "host:port", split it
$dbServerRaw = getenv('MW_DB_SERVER') ?: 'localhost';
$parts = explode(':', $dbServerRaw, 2);
$wgDBserver = $parts[0];
$wgDBport = isset($parts[1]) ? $parts[1] : '3306';
$wgDBtype = 'mysql';
$wgDBname = getenv('MW_DB_NAME') ?: 'railway';
$wgDBuser = getenv('MW_DB_USER') ?: 'root';
$wgDBpassword = getenv('MW_DB_PASS') ?: '';
$wgDBTableOptions = "ENGINE=InnoDB, DEFAULT CHARSET=binary";

$wgSecretKey = getenv('MW_SECRET_KEY') ?: 'changeme-in-env-please';
$wgUpgradeKey = getenv('MW_UPGRADE_KEY') ?: 'changeme-in-env';
$wgAuthenticationTokenVersion = "1";

$wgMainCacheType = CACHE_NONE;
$wgMemCachedServers = [];

$wgLanguageCode = 'en';
$wgDefaultSkin = 'vector';

# Behind Railway edge proxy — trust X-Forwarded-* so $wgServer works over https
$wgUsePrivateIPs = false;
if ( !empty($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https' ) {
    $_SERVER['HTTPS'] = 'on';
}

# Allow DISPLAYTITLE to hide namespace prefix (e.g. Card:Ratchanter -> Ratchanter)
$wgAllowDisplayTitle = true;
$wgRestrictDisplayTitle = false;

# Permissions — API + edit usable by logged-in users (default is fine)
$wgGroupPermissions['*']['createaccount'] = false;
$wgGroupPermissions['*']['edit'] = false;

# Skins
wfLoadSkin('Vector');
$wgVectorResponsive = true;
$wgVectorDefaultSkinVersion = '2';  # Vector 2022 — built-in mobile support

# Extensions
wfLoadExtension('ParserFunctions');
$wgPFEnableStringFunctions = true;

# Load Semantic MediaWiki
wfLoadExtension('SemanticMediaWiki');
$smwNamespace = parse_url($wgServer, PHP_URL_HOST) ?: 'grid-tactics.wiki';
enableSemantics( $smwNamespace );
