<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\UrlQueryInput;

final class UrlQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'page' => ['sometimes', 'nullable'],
            'per_page' => ['sometimes', 'nullable'],
            'sort_by' => ['sometimes', 'nullable'],
            'sort_order' => ['sometimes', 'nullable'],
            'shop' => ['sometimes', 'nullable'],
            'url_type' => ['sometimes', 'nullable'],
            'search' => ['sometimes', 'nullable'],
            'is_book' => ['sometimes', 'nullable'],
            'has_book' => ['sometimes'],
            'failing' => ['sometimes'],
        ];
    }

    public function toDto(): UrlQueryInput
    {
        $this->validated();

        return new UrlQueryInput(
            page: max(1, $this->integer('page', 1)),
            perPage: max(1, min($this->integer('per_page', 30), 200)),
            sortBy: $this->filled('sort_by')
                ? $this->string('sort_by')->toString()
                : 'discovered',
            sortOrder: $this->string('sort_order')->toString(),
            shop: $this->string('shop')->toString(),
            urlType: $this->string('url_type')->toString(),
            search: $this->string('search')->toString(),
            isBook: $this->string('is_book')->toString(),
            hasBook: $this->boolean('has_book'),
            failing: $this->boolean('failing'),
        );
    }
}
