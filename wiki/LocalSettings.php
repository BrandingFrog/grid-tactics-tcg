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

# Cache — use Redis if available (requires php-redis), fall back to APCu, then none
$redisServer = getenv('MW_REDIS_SERVER');
$redisPass   = getenv('MW_REDIS_PASSWORD');
if ( $redisServer && extension_loaded('redis') ) {
    $wgObjectCaches['redis'] = [
        'class'       => 'RedisBagOStuff',
        'servers'     => [ $redisServer ],
        'password'    => $redisPass ?: null,
        'persistent'  => true,
    ];
    $wgMainCacheType    = 'redis';
    $wgSessionCacheType = 'redis';
    $wgParserCacheType  = 'redis';
} elseif ( function_exists('apcu_fetch') ) {
    $wgMainCacheType = CACHE_ACCEL;
} else {
    $wgMainCacheType = CACHE_NONE;
}
$wgMemCachedServers = [];

# Parser cache — keep compiled pages for 7 days (default 1 day)
$wgParserCacheExpireTime = 86400 * 7;

# Sidebar cache — avoid re-rendering navigation on every page load
$wgEnableSidebarCache = true;
$wgSidebarCacheExpiry = 86400;

# ResourceLoader — aggressive caching for versioned assets
$wgResourceLoaderMaxage = [
    'versioned'   => 30 * 24 * 3600,
    'unversioned' => 300,
];

$wgLanguageCode = 'en';
$wgDefaultSkin = 'citizen';

# Behind Railway edge proxy — trust X-Forwarded-* so $wgServer works over https
$wgUsePrivateIPs = false;
if ( !empty($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https' ) {
    $_SERVER['HTTPS'] = 'on';
}

# Allow DISPLAYTITLE to hide namespace prefix (e.g. Card:Ratchanter -> Ratchanter)
$wgAllowDisplayTitle = true;
$wgRestrictDisplayTitle = false;

# Job queue — run 1 job per request (lighter than 2, still drains queue)
$wgJobRunRate = 1;

# Permissions — API + edit usable by logged-in users (default is fine)
$wgGroupPermissions['*']['createaccount'] = false;
$wgGroupPermissions['*']['edit'] = false;

# Skins
wfLoadSkin('Citizen');
$wgCitizenThemeDefault = 'dark';

# Extensions
wfLoadExtension('ParserFunctions');
$wgPFEnableStringFunctions = true;

# Load Semantic MediaWiki
wfLoadExtension('SemanticMediaWiki');
$smwNamespace = parse_url($wgServer, PHP_URL_HOST) ?: 'grid-tactics.wiki';
enableSemantics( $smwNamespace );

# --- SMW Performance Tuning ---
# Cache query results in Redis (uses $wgMainCacheType backend)
$smwgQueryResultCacheType = CACHE_ANYTHING;
$smwgQueryResultCacheLifetime = 3600;

# Auto-invalidate cached results when properties change
$smwgEnabledQueryDependencyLinksStore = true;

# Query limits — sensible defaults for a ~20 card wiki
$smwgQMaxSize = 16;
$smwgQDefaultLimit = 50;

# --- Semantic Drilldown (Phase 9.2) -------------------------------------------
# Faceted card search at Special:BrowseData/Card. Configured via {{#drilldowninfo:}}
# on Category:Card (see wiki/sync/sync_filters.py). SD 5.0.0-beta1 @ 7ca8f802.
# NOTE: leave this block clearly delimited so Phase 9.2 rollback is a clean
# section-cut. Do NOT merge these assignments into the SMW block above.
wfLoadExtension( 'SemanticDrilldown' );
$sdgNumRangesForNumberFilters = 5;   # default 6 → 5 so ManaCost (0-10) buckets cleanly (0-2/3-4/5-6/7-8/9-10)
$sdgNumResultsPerPage         = 50;  # default 250 → 50 (we have ~36 cards)
$sdgHideFiltersWithoutValues  = true; # cleaner drilling UX — drop facets with zero values in current result set

# --- Error logging (operational) ---------------------------------------------
# Gated on MW_DEBUG=1 env var so it can be turned off once the investigation
# is done. When enabled:
#   - exception traces show up in the HTTP 500 response body
#   - PHP errors + MediaWiki debug log are funneled to stderr, which Railway
#     captures in its log stream (fetchable via deploymentLogs GraphQL query)
#   - SMW-specific log groups are included because the current 500 is on
#     Category:Card, which is an SMW-heavy page
$mwDebug = getenv('MW_DEBUG') === '1';
if ( $mwDebug ) {
    $wgShowExceptionDetails = true;
    $wgShowDBErrorBacktrace = true;
    $wgDevelopmentWarnings  = false;  # deprecation noise, not useful here

    ini_set('log_errors', '1');
    ini_set('error_log', 'php://stderr');

    $wgDebugLogFile = 'php://stderr';
    $wgDebugLogGroups = [
        'exception' => 'php://stderr',
        'error'     => 'php://stderr',
        'fatal'     => 'php://stderr',
        'smw'       => 'php://stderr',
        'SMW'       => 'php://stderr',
    ];
}
