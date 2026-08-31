FROM php:8.4-cli AS base

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

COPY composer.json composer.lock ./

RUN composer install --no-dev --no-scripts --no-autoloader

COPY . .

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD php -r 'exit((new PDO(sprintf("pgsql:host=%s;port=%s;dbname=%s", getenv("DB_HOST"), getenv("DB_PORT") ?: 5432, getenv("DB_DATABASE")), getenv("DB_USERNAME"), getenv("DB_PASSWORD"))) ? 0 : 1);'

CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8000"]
