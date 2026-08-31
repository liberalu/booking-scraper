<?php

declare(strict_types=1);

use App\Http\Controllers\Api\BookExportController;
use App\Http\Controllers\Api\BooksController;
use App\Http\Controllers\Api\CronController;
use App\Http\Controllers\Api\CronMutationsController;
use App\Http\Controllers\Api\IssueMutationsController;
use App\Http\Controllers\Api\IssuesController;
use App\Http\Controllers\Api\OverviewController;
use App\Http\Controllers\Api\PricesController;
use App\Http\Controllers\Api\RepeatedFailuresController;
use App\Http\Controllers\Api\RunLiveController;
use App\Http\Controllers\Api\RunMutationsController;
use App\Http\Controllers\Api\RunsController;
use App\Http\Controllers\Api\RunSpawnController;
use App\Http\Controllers\Api\RunUrlsController;
use App\Http\Controllers\Api\ScheduleController;
use App\Http\Controllers\Api\ShopBooksController;
use App\Http\Controllers\Api\ShopsController;
use App\Http\Controllers\Api\UrlDetailController;
use App\Http\Controllers\Api\UrlsController;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Route;
use Symfony\Component\HttpFoundation\Response;

foreach (['book', 'run', 'url', 'issue', 'job', 'shopBook'] as $numericParameter) {
    Route::pattern($numericParameter, '[0-9]+');
}

Route::get('/overview', OverviewController::class);

Route::get('/books/stats', [BooksController::class, 'stats']);
Route::get('/books/years', [BooksController::class, 'years']);
Route::get('/books/export', BookExportController::class);
Route::get('/books', [BooksController::class, 'index']);
Route::get('/books/{book}/prices', [BooksController::class, 'prices']);
Route::get('/books/{book}', [BooksController::class, 'show']);
Route::get('/schedule', ScheduleController::class);

Route::get('/runs/repeated-failures', RepeatedFailuresController::class);
Route::get('/runs', [RunsController::class, 'index']);
Route::get('/runs/{run}/books', [RunsController::class, 'books']);
Route::get('/runs/{run}/urls', RunUrlsController::class);
Route::get('/runs/{run}/live', RunLiveController::class);
Route::get('/runs/{run}', [RunsController::class, 'show']);
Route::get('/shops', [ShopsController::class, 'index']);
Route::get('/shops/{shop}', [ShopsController::class, 'show']);
Route::get('/shop-books', [ShopBooksController::class, 'index']);
Route::get('/shop-books/{shopBook}', [ShopBooksController::class, 'show']);
Route::get('/urls', [UrlsController::class, 'index']);
Route::get('/urls/{url}', UrlDetailController::class);

Route::get('/issues/groups', [IssuesController::class, 'groups']);
Route::get('/issues/trend', [IssuesController::class, 'trend']);
Route::get('/issues', [IssuesController::class, 'index']);
Route::get('/issues/{issue}', [IssuesController::class, 'show']);
Route::get('/prices', PricesController::class);
Route::get('/cron', [CronController::class, 'index']);
Route::get('/cron/{job}/detail', [CronController::class, 'show']);

Route::post('/books', [BooksController::class, 'store']);

Route::middleware('throttle:spawn')->group(function (): void {
    Route::post('/runs', [RunSpawnController::class, 'store']);
    Route::post('/runs/{run}/rerun', [RunSpawnController::class, 'rerun']);
    Route::post('/runs/{run}/continue', [RunSpawnController::class, 'continueRun']);
    Route::post('/runs/{run}/retry', [RunSpawnController::class, 'retry']);
});
Route::post('/runs/{run}/stop', [RunMutationsController::class, 'stop']);
Route::post('/runs/{run}/pause', [RunMutationsController::class, 'pause']);
Route::post('/runs/{run}/resume', [RunMutationsController::class, 'resume']);
Route::post('/runs/{run}/failures/ack', [RunMutationsController::class, 'ackFailures']);
Route::post('/shop-books/{shopBook}/unlink-canonical', [ShopBooksController::class, 'unlinkCanonical']);

Route::post('/cron/{job}/toggle', [CronMutationsController::class, 'toggle']);
Route::post('/cron', [CronMutationsController::class, 'store']);
Route::patch('/cron/{job}', [CronMutationsController::class, 'update']);
Route::delete('/cron/{job}', [CronMutationsController::class, 'destroy']);
Route::post('/issues/bulk-rescrape', [IssueMutationsController::class, 'bulkRescrape']);
Route::post('/issues/bulk-acknowledge', [IssueMutationsController::class, 'bulkAcknowledge']);
Route::post('/issues/bulk-unacknowledge', [IssueMutationsController::class, 'bulkUnacknowledge']);
Route::patch('/issues/{issue}/lifecycle', [IssueMutationsController::class, 'lifecycle']);
Route::patch('/issues/{issue}/snooze', [IssueMutationsController::class, 'snooze']);

Route::fallback(static fn (): JsonResponse => new JsonResponse(
    ['detail' => 'Not found'],
    Response::HTTP_NOT_FOUND,
));
