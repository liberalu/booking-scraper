<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\BookQueryRequest;
use App\Http\Requests\BookStoreRequest;
use App\Models\Book;
use App\Queries\Api\BooksQuery;
use App\Services\Books\CreateBookService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class BooksController
{
    public function __construct(
        private BooksQuery $query,
        private CreateBookService $createBook,
    ) {}

    public function index(BookQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->index($request->toDto()), Response::HTTP_OK);
    }

    public function stats(): JsonResponse
    {
        return new JsonResponse($this->query->stats(), Response::HTTP_OK);
    }

    public function years(): JsonResponse
    {
        return new JsonResponse($this->query->years(), Response::HTTP_OK);
    }

    public function show(Book $book): JsonResponse
    {
        return new JsonResponse($this->query->show($book), Response::HTTP_OK);
    }

    public function prices(Book $book): JsonResponse
    {
        return new JsonResponse($this->query->prices($book), Response::HTTP_OK);
    }

    public function store(BookStoreRequest $request): JsonResponse
    {
        return new JsonResponse(
            $this->createBook->create($request->toDto()),
            Response::HTTP_OK,
        );
    }
}
