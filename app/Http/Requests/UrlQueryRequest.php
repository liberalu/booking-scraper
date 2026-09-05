<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\UrlQueryInput;
use Illuminate\Validation\Rule;

final class UrlQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'page' => ['sometimes', 'nullable', 'integer', 'min:1', 'max:100000'],
            'per_page' => ['sometimes', 'nullable', 'integer', 'between:1,200'],
            'sort_by' => ['sometimes', 'nullable', 'string', Rule::in(['discovered', 'url', 'fails', 'book'])],
            'sort_order' => ['sometimes', 'nullable', 'string', Rule::in(['asc', 'desc'])],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'url_type' => ['sometimes', 'nullable', 'string', Rule::in(['all', 'unknown', 'product', 'product_partial', 'non_product', 'unreachable'])],
            'search' => ['sometimes', 'nullable', 'string', 'max:2000'],
            'is_book' => ['sometimes', 'nullable', 'string', Rule::in(['all', 'book', 'not_book'])],
            'has_book' => ['sometimes', 'boolean'],
            'failing' => ['sometimes', 'boolean'],
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
