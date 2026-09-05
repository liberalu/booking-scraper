FROM node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY public/static/hifi public/static/hifi
COPY tools/build-frontend.mjs tools/build-frontend.mjs
RUN npm run build

FROM php@sha256:59fa733c9af643a122f8a9976119460e35ce76dd0a3f2b9c8f75af8e361a54e2 AS base

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libpq-dev libxml2-dev libonig-dev unzip nginx curl tini; \
    docker-php-ext-install -j"$(nproc)" pdo_pgsql mbstring pcntl dom; \
    apt-get purge -y --auto-remove libxml2-dev libonig-dev; \
    rm -rf /var/lib/apt/lists/*

COPY --from=composer@sha256:743aebe48ca67097c36819040633ea77e44a561eca135e4fc84c002e63a1ba07 /usr/bin/composer /usr/bin/composer

ENV COMPOSER_ALLOW_SUPERUSER=1 \
    COMPOSER_NO_INTERACTION=1

WORKDIR /app

COPY composer.json composer.lock ./

RUN composer install --no-dev --no-scripts --no-autoloader

COPY . .
COPY --from=frontend /app/public/build /app/public/build

RUN set -eux; \
    groupadd --gid 10001 app; \
    useradd --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app; \
    mkdir -p storage/logs \
             storage/framework/sessions \
             storage/framework/views \
             storage/framework/cache/data \
             bootstrap/cache \
             /var/log/scrapy_runs; \
    chown -R app:app /app /var/log/scrapy_runs; \
    chmod -R u=rwX,g=rX,o= storage bootstrap/cache /var/log/scrapy_runs

RUN composer dump-autoload --no-dev --optimize

ENV SPAWN_LOG_DIR=/var/log/scrapy_runs

COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/php-production.ini /usr/local/etc/php/conf.d/production.ini
COPY docker/start-dashboard /usr/local/bin/start-dashboard

RUN chmod 0555 /usr/local/bin/start-dashboard

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8000/up >/dev/null || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["start-dashboard"]
