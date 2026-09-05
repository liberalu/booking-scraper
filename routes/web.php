<?php

declare(strict_types=1);

use App\Http\Controllers\Web\LegacyFormsController;
use Illuminate\Http\Request;
use Illuminate\Http\Response as HttpResponse;
use Illuminate\Support\Facades\Response;
use Illuminate\Support\Facades\Route;
use Symfony\Component\HttpFoundation\BinaryFileResponse;
use Symfony\Component\HttpFoundation\Response as HttpStatus;

Route::post('/shops/{shop}/rate-settings', [LegacyFormsController::class, 'rateSettings'])
    ->missing(static fn (): HttpResponse => new HttpResponse(
        '<p class="error">Shop not found</p>',
        HttpResponse::HTTP_NOT_FOUND,
        ['Content-Type' => 'text/html; charset=utf-8'],
    ));

Route::middleware('throttle:spawn')->group(function (): void {
    Route::post('/scrape/filtered', [LegacyFormsController::class, 'scrapeFiltered']);
    Route::post('/scrape/unknown-urls', [LegacyFormsController::class, 'scrapeUnknownUrls']);
    Route::post('/scrape/url/{url}', [LegacyFormsController::class, 'scrapeUrl']);
});

Route::get('/validation', function (Request $request): mixed {
    $query = $request->getQueryString();

    return redirect(
        '/issues'.($query !== null ? "?{$query}" : ''),
        HttpStatus::HTTP_MOVED_PERMANENTLY,
    );
});
Route::get('/shops/{shop}/not-listed', fn (string $shop): mixed => redirect(
    "/shops/{$shop}",
    HttpStatus::HTTP_MOVED_PERMANENTLY,
));

Route::get('/{any?}', function (): BinaryFileResponse {
    $built = public_path('build/hifi/index.html');

    return Response::file(is_file($built) ? $built : public_path('static/hifi/index.html'));
})
    ->where('any', '^(?!api).*$');
