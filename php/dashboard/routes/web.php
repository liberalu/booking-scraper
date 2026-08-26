<?php

declare(strict_types=1);

use App\Http\Controllers\Api\BooksController;
use App\Http\Controllers\Api\CronController;
use App\Http\Controllers\Api\CronMutationsController;
use App\Http\Controllers\Api\IssueMutationsController;
use App\Http\Controllers\Api\IssuesController;
use App\Http\Controllers\Api\LegacyFormsController;
use App\Http\Controllers\Api\OverviewController;
use App\Http\Controllers\Api\PricesController;
use App\Http\Controllers\Api\RepeatedFailuresController;
use App\Http\Controllers\Api\RunLiveController;
use App\Http\Controllers\Api\RunMutationsController;
use App\Http\Controllers\Api\RunSpawnController;
use App\Http\Controllers\Api\RunUrlsController;
use App\Http\Controllers\Api\RunsController;
use App\Http\Controllers\Api\ScheduleController;
use App\Http\Controllers\Api\ShopBooksController;
use App\Http\Controllers\Api\ShopsController;
use App\Http\Controllers\Api\UrlDetailController;
use App\Http\Controllers\Api\UrlsController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\Facades\Response;

/**
 * The React SPA in public/static/hifi is served as-is; this app only has to
 * serve the JSON API it calls.
 *
 * That tree used to be a symlink into book_scraper/dashboard/static, so both
 * dashboards rendered from one frontend source and the comparison was of the
 * API alone. It became canonical here when Python was removed — the symlink
 * was the one thing that would have taken the SPA down with it.
 */

// define(), not const: Laravel reloads the route file for every application
// instance it boots, and a file-scope `const` fatals on the second one. Only
// showed up once a second app-booting test existed.
defined('SPA_INDEX') || define(
    'SPA_INDEX',
    __DIR__ . '/../public/static/hifi/index.html'
);

Route::prefix('api')->group(function (): void {
    Route::get('/overview', OverviewController::class);
    // Static segments before the {id} route, or 'stats' matches as an id.
    Route::get('/books/stats', [BooksController::class, 'stats']);
    Route::get('/books/years', [BooksController::class, 'years']);
    Route::get('/books/export', [BooksController::class, 'export']);
    Route::get('/books', [BooksController::class, 'index']);
    Route::get('/books/{book}/prices', [BooksController::class, 'prices']);
    Route::get('/books/{book}', [BooksController::class, 'show']);
    Route::get('/schedule', ScheduleController::class);
    // Must precede /runs/{id} style routes.
    Route::get('/runs/repeated-failures', RepeatedFailuresController::class);
    Route::get('/runs', [RunsController::class, 'index']);
    Route::get('/runs/{run}/books', [RunsController::class, 'books']);
    Route::get('/runs/{run}/urls', RunUrlsController::class);
    Route::get('/runs/{run}/live', RunLiveController::class);
    Route::get('/runs/{run}', [RunsController::class, 'show']);
    Route::get('/shops', [ShopsController::class, 'index']);
    Route::get('/shops/{shop}', [ShopsController::class, 'show']);
    Route::get('/shop-books', [ShopBooksController::class, 'index']);
    Route::get('/shop-books/{book}', [ShopBooksController::class, 'show']);
    Route::get('/urls', [UrlsController::class, 'index']);
    Route::get('/urls/{url}', UrlDetailController::class);
    // Static segments before {id}, or 'groups' matches as an id.
    Route::get('/issues/groups', [IssuesController::class, 'groups']);
    Route::get('/issues/trend', [IssuesController::class, 'trend']);
    Route::get('/issues', [IssuesController::class, 'index']);
    Route::get('/issues/{issue}', [IssuesController::class, 'show']);
    Route::get('/prices', PricesController::class);
    Route::get('/cron', [CronController::class, 'index']);
    Route::get('/cron/{job}/detail', [CronController::class, 'show']);

    // ── Mutations ────────────────────────────────────────────────────────
    // Everything here is a pure database write; the ones that spawn a crawl
    // fall through to the catch-all below.
    Route::post('/books', [BooksController::class, 'store']);
    Route::post('/runs', [RunSpawnController::class, 'store']);
    Route::post('/runs/{run}/rerun', [RunSpawnController::class, 'rerun']);
    Route::post('/runs/{run}/continue', [RunSpawnController::class, 'continueRun']);
    Route::post('/runs/{run}/retry', [RunSpawnController::class, 'retry']);
    Route::post('/runs/{run}/stop', [RunMutationsController::class, 'stop']);
    Route::post('/runs/{run}/pause', [RunMutationsController::class, 'pause']);
    Route::post('/runs/{run}/resume', [RunMutationsController::class, 'resume']);
    Route::post('/runs/{run}/failures/ack', [RunMutationsController::class, 'ackFailures']);
    Route::post('/shop-books/{book}/unlink-canonical', [ShopBooksController::class, 'unlinkCanonical']);
    // Static segments before {job}, or 'toggle' would match as an id.
    Route::post('/cron/{job}/toggle', [CronMutationsController::class, 'toggle']);
    Route::post('/cron', [CronMutationsController::class, 'store']);
    Route::patch('/cron/{job}', [CronMutationsController::class, 'update']);
    Route::delete('/cron/{job}', [CronMutationsController::class, 'destroy']);
    Route::post('/issues/bulk-rescrape', [IssueMutationsController::class, 'bulkRescrape']);
    Route::post('/issues/bulk-acknowledge', [IssueMutationsController::class, 'bulkAcknowledge']);
    Route::post('/issues/bulk-unacknowledge', [IssueMutationsController::class, 'bulkUnacknowledge']);
    Route::patch('/issues/{issue}/lifecycle', [IssueMutationsController::class, 'lifecycle']);
    Route::patch('/issues/{issue}/snooze', [IssueMutationsController::class, 'snooze']);

    // Mutations drive the crawler (spawning scrapy, pausing runs, toggling
    // cron). The PHP crawler does not exist yet, so these answer honestly
    // instead of 404ing and looking like a routing bug.
    Route::any('/{any}', function (Request $request) {
        $method = $request->method();
        if ($method !== 'GET') {
            return Response::json([
                'detail' => 'Not implemented in the PHP dashboard: this action '
                    . 'drives the crawler, which is not ported yet. Use the '
                    . 'Python dashboard on :8001 for write operations.',
                'php_port' => 'read-only',
            ], 501);
        }

        return Response::json([
            'detail' => "GET /api/{$request->path()} is not ported yet.",
            'php_port' => 'partial',
        ], 501);
    })->where('any', '.*');
});

// The pre-SPA form endpoints, outside /api: they answer with HTML or a 303
// redirect. `rate-settings` is the only UI for the shop_settings override.
Route::post('/shops/{shop}/rate-settings', [LegacyFormsController::class, 'rateSettings']);
Route::post('/scrape/filtered', [LegacyFormsController::class, 'scrapeFiltered']);
Route::post('/scrape/unknown-urls', [LegacyFormsController::class, 'scrapeUnknownUrls']);
Route::post('/scrape/url/{url}', [LegacyFormsController::class, 'scrapeUrl']);

// Renamed pages, kept as 301s so old bookmarks and links still land. These
// must precede the SPA catch-all, which would otherwise answer 200 with the
// shell at the old path and never redirect.
Route::get('/validation', function (Request $request): mixed {
    $query = $request->getQueryString();

    return redirect('/issues' . ($query !== null ? "?{$query}" : ''), 301);
});
Route::get('/shops/{shop}/not-listed', fn (string $shop): mixed
    => redirect("/shops/{$shop}", 301));

// Client-side routing: every non-API path renders the SPA shell.
Route::get('/{any?}', fn (): mixed => Response::file(SPA_INDEX))
    ->where('any', '^(?!api).*$');
