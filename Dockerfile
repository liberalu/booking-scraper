# The PHP stack: one image, three services (dashboard, scheduler, reaper).
#
# There is no separate crawler service. Crawls are spawned as child processes
# by whichever container asked for them — CrawlSpawner runs bin/crawl directly
# — so the image has to carry the whole tree, and it does. The trade-off is
# recorded in docker-compose.yml.
#
# 8.4, not 8.5: roach-php caps there and composer refuses to resolve against
# newer. The same pin the Makefile applies on a developer machine.
FROM php:8.4-cli AS base

# pcntl is not optional. The watchdog runs in a forked child, and without it
# the crawl has no heartbeat and no stall detection — it degrades quietly
# behind a function_exists() guard, which is the worst way to lose it.
#
# dom + mbstring: the parsers walk HTML through DomCrawler and normalise
# Lithuanian diacritics. pdo_pgsql: everything.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libpq-dev libxml2-dev libonig-dev unzip; \
    docker-php-ext-install -j"$(nproc)" pdo_pgsql mbstring pcntl dom; \
    apt-get purge -y --auto-remove libxml2-dev libonig-dev; \
    rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

ENV COMPOSER_ALLOW_SUPERUSER=1 \
    COMPOSER_NO_INTERACTION=1

WORKDIR /app

# --- dependencies -----------------------------------------------------------
#
# Manifests first, so a source change does not re-resolve every package. One
# project now: the library, the crawler and the dashboard were three composer
# projects wired together with path repositories until they were merged.
COPY composer.json composer.lock ./

# --no-scripts and --no-autoloader: Laravel's package discovery and the
# optimised autoloader both need the source, which arrives in the next layer.
RUN composer install --no-dev --no-scripts --no-autoloader

# --- source -----------------------------------------------------------------
#
# config/ holds Laravel's *.php config AND the shops' TOML, which is read as
# dirname(__DIR__, 2) . '/config' from app/Support. Laravel only ever loads
# *.php from there, so the two coexist.
COPY . .

# Before dump-autoload, not after: Laravel's package discovery runs as a
# post-autoload-dump script and writes bootstrap/cache/packages.php, so the
# directory has to exist first. .dockerignore keeps the host's copy out —
# built there it lists dev-only providers the image never installs.
# The whole storage skeleton, not just views: .dockerignore keeps the host's
# storage/framework out (it holds a developer's sessions and compiled views),
# so every directory Laravel writes to has to be created here. Miss
# framework/sessions and every page is a 500 on file_put_contents.
RUN set -eux; \
    mkdir -p storage/logs \
             storage/framework/sessions \
             storage/framework/views \
             storage/framework/cache/data \
             bootstrap/cache \
             /var/log/scrapy_runs; \
    chmod -R 0777 storage bootstrap/cache

RUN composer dump-autoload --no-dev --optimize

ENV SPAWN_LOG_DIR=/var/log/scrapy_runs

# One healthcheck for all three services: can this container reach the
# database it was pointed at? A dashboard that boots but cannot query is the
# failure worth catching, and it is the same question for the scheduler.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD php -r 'exit((new PDO(sprintf("pgsql:host=%s;port=%s;dbname=%s", getenv("DB_HOST"), getenv("DB_PORT") ?: 5432, getenv("DB_DATABASE")), getenv("DB_USERNAME"), getenv("DB_PASSWORD"))) ? 0 : 1);'

CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8000"]
