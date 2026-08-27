<?php

declare(strict_types=1);

use App\Http\Controllers\Api\LegacyFormsController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\Facades\Response;

/**
 * Browser-facing routes: the React SPA shell in public/static/hifi, the
 * pre-SPA form posts, and the renamed-page redirects. The JSON API the SPA
 * calls lives in routes/api.php.
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
