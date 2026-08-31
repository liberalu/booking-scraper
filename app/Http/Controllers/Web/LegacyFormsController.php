<?php

declare(strict_types=1);

namespace App\Http\Controllers\Web;

use App\DTO\LegacyActionKind;
use App\Exceptions\ActionFailed;
use App\Exceptions\FailureKind;
use App\Http\Requests\LegacyFormRequest;
use App\Models\DiscoveredUrl;
use App\Models\Shop;
use App\Services\Legacy\LegacyFormsService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Response;

final readonly class LegacyFormsController
{
    public function __construct(private LegacyFormsService $service) {}

    public function rateSettings(LegacyFormRequest $request, Shop $shop): Response
    {
        try {
            $action = $this->service->rateSettings($request->toDto(), $shop);
        } catch (ActionFailed $failure) {
            $detail = $failure->payload['detail'] ?? 'Request failed';

            return new Response(
                '<p class="error">'.e(is_string($detail) ? $detail : 'Request failed').'</p>',
                $failure->kind === FailureKind::NotFound
                    ? Response::HTTP_NOT_FOUND
                    : Response::HTTP_BAD_REQUEST,
                ['Content-Type' => 'text/html; charset=utf-8'],
            );
        }

        return new Response(
            $action->stringPayload(),
            Response::HTTP_OK,
            ['Content-Type' => 'text/html; charset=utf-8'],
        );
    }

    public function scrapeUrl(DiscoveredUrl $url): RedirectResponse
    {
        $action = $this->service->scrapeUrl($url);

        return new RedirectResponse($action->stringPayload(), Response::HTTP_SEE_OTHER);
    }

    public function scrapeUnknownUrls(LegacyFormRequest $request): RedirectResponse
    {
        $action = $this->service->scrapeUnknownUrls($request->toDto());

        return new RedirectResponse($action->stringPayload(), Response::HTTP_SEE_OTHER);
    }

    public function scrapeFiltered(LegacyFormRequest $request): JsonResponse|RedirectResponse
    {
        $action = $this->service->scrapeFiltered($request->toDto());
        if ($action->kind === LegacyActionKind::Accepted) {
            return new JsonResponse($action->payload, Response::HTTP_ACCEPTED);
        }

        return new RedirectResponse($action->stringPayload(), Response::HTTP_SEE_OTHER);
    }
}
