<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\BookStoreInput;

final class BookStoreRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'title' => ['sometimes', 'nullable'],
            'isbn' => ['sometimes', 'nullable'],
            'year' => ['sometimes', 'nullable'],
            'author' => ['sometimes', 'nullable'],
            'publisher' => ['sometimes', 'nullable'],
        ];
    }

    public function toDto(): BookStoreInput
    {
        $this->validated();

        return new BookStoreInput(
            title: $this->string('title')->toString(),
            isbn: $this->string('isbn')->toString(),
            year: $this->filled('year') ? $this->integer('year') : null,
            author: $this->string('author')->toString(),
            publisher: $this->string('publisher')->toString(),
        );
    }
}
