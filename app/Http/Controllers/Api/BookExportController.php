<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\BookQueryRequest;
use App\Queries\Api\BooksQuery;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpFoundation\StreamedResponse;

final readonly class BookExportController
{
    public function __construct(private BooksQuery $query) {}

    public function __invoke(BookQueryRequest $request): StreamedResponse
    {
        $download = $this->query->export($request->toDto());

        return new StreamedResponse(
            $download->writer,
            Response::HTTP_OK,
            [
                ...$download->headers,
                'Content-Disposition' => "attachment; filename={$download->filename}",
            ],
        );
    }
}
