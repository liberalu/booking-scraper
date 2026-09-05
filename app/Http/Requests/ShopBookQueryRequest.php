<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\ShopBookQueryInput;
use Illuminate\Validation\Rule;

final class ShopBookQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'page' => ['sometimes', 'nullable', 'integer', 'min:1', 'max:100000'],
            'per_page' => ['sometimes', 'nullable', 'integer', 'between:1,200'],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'search' => ['sometimes', 'nullable', 'string', 'max:500'],
            'category' => ['sometimes', 'nullable', 'string', 'max:500'],
            'type_filter' => ['sometimes', 'nullable', 'string', 'max:100'],
            'format_filter' => ['sometimes', 'nullable', 'string', 'max:100'],
            'missing_field' => ['sometimes', 'nullable', 'string', Rule::in(['any', 'title', 'author', 'isbn', 'publisher', 'year', 'price', 'format', 'image_url'])],
            'active' => ['sometimes', 'nullable', 'string', Rule::in(['true', 'false', 'all'])],
            'linked' => ['sometimes', 'nullable', 'string', Rule::in(['linked', 'not_linked', 'all'])],
            'sort_by' => ['sometimes', 'nullable', 'string', Rule::in(['id', 'title', 'author', 'price', 'last_seen_at'])],
            'sort_order' => ['sometimes', 'nullable', 'string', Rule::in(['asc', 'desc'])],
            'has_isbn' => ['sometimes', 'boolean'],
            'url_unreachable' => ['sometimes', 'boolean'],
        ];
    }

    public function toDto(): ShopBookQueryInput
    {
        $this->validated();

        return new ShopBookQueryInput(
            page: max(1, $this->integer('page', 1)),
            perPage: max(1, min($this->integer('per_page', 30), 200)),
            shop: $this->string('shop')->toString(),
            search: $this->string('search')->toString(),
            category: trim($this->string('category')->toString()),
            type: $this->string('type_filter')->toString(),
            format: $this->string('format_filter')->toString(),
            missingField: $this->string('missing_field')->toString(),
            active: $this->string('active')->toString(),
            linked: $this->string('linked')->toString(),
            sortBy: $this->string('sort_by')->toString(),
            sortOrder: $this->string('sort_order')->toString(),
            hasIsbn: $this->boolean('has_isbn'),
            urlUnreachable: $this->boolean('url_unreachable'),
        );
    }
}
