<?php

use App\Exceptions\ActionFailed;
use App\Exceptions\FailureKind;
use App\Http\Middleware\DashboardBasicAuth;
use App\Models\Book;
use App\Models\CronJob;
use App\Models\DiscoveredUrl;
use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Models\ShopBook;
use App\Models\ValidationIssue;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware): void {

        $middleware->preventRequestForgery(except: [
            'scrape/*',
            'shops/*/rate-settings',
        ]);

        $middleware->web(append: DashboardBasicAuth::class);
        $middleware->api(
            append: DashboardBasicAuth::class,
            prepend: 'throttle:300,1',
        );
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->render(function (ActionFailed $failure): JsonResponse {
            return new JsonResponse($failure->payload, match ($failure->kind) {
                FailureKind::BadRequest => Response::HTTP_BAD_REQUEST,
                FailureKind::Conflict => Response::HTTP_CONFLICT,
                FailureKind::NotFound => Response::HTTP_NOT_FOUND,
                FailureKind::PayloadTooLarge => Response::HTTP_REQUEST_ENTITY_TOO_LARGE,
                FailureKind::Unavailable => Response::HTTP_SERVICE_UNAVAILABLE,
                FailureKind::Unprocessable => Response::HTTP_UNPROCESSABLE_ENTITY,
            });
        });

        $exceptions->render(function (NotFoundHttpException $exception, Request $request): ?JsonResponse {
            $previous = $exception->getPrevious();
            if (! $previous instanceof ModelNotFoundException) {
                return null;
            }

            $detail = match ($previous->getModel()) {
                Book::class => 'Book not found',
                CronJob::class => 'Job not found',
                DiscoveredUrl::class => 'URL not found',
                ScrapeRun::class => 'Run not found',
                Shop::class => 'Shop not found',
                ShopBook::class => $request->is('api/shop-books/*/unlink-canonical')
                    ? 'shop_book not found'
                    : 'Book not found',
                ValidationIssue::class => 'Issue not found',
                default => 'Not found',
            };

            return new JsonResponse(['detail' => $detail], Response::HTTP_NOT_FOUND);
        });

        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );
    })->create();
