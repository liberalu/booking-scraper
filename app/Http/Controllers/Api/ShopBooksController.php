<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\ShopBookQueryRequest;
use App\Models\ShopBook;
use App\Queries\Api\ShopBooksQuery;
use App\Services\Shops\UnlinkCanonicalService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class ShopBooksController
{
    public function __construct(
        private ShopBooksQuery $query,
        private UnlinkCanonicalService $unlinkCanonical,
    ) {}

    public function index(ShopBookQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->index($request->toDto()), Response::HTTP_OK);
    }

    public function show(ShopBook $shopBook): JsonResponse
    {
        return new JsonResponse($this->query->show($shopBook), Response::HTTP_OK);
    }

    public function unlinkCanonical(ShopBook $shopBook): JsonResponse
    {
        return new JsonResponse(
            $this->unlinkCanonical->unlink($shopBook),
            Response::HTTP_OK,
        );
    }
}
