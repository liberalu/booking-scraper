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
            'title' => ['required', 'string', 'max:1000'],
            'isbn' => ['sometimes', 'nullable', 'string', 'max:32'],
            'year' => ['sometimes', 'nullable', 'integer', 'between:1000,2100'],
            'author' => ['sometimes', 'nullable', 'string', 'max:1000'],
            'publisher' => ['sometimes', 'nullable', 'string', 'max:500'],
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
