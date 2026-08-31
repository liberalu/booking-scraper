<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\ShopBookQueryInput;

final class ShopBookQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'page' => ['sometimes', 'nullable'],
            'per_page' => ['sometimes', 'nullable'],
            'shop' => ['sometimes', 'nullable'],
            'search' => ['sometimes', 'nullable'],
            'category' => ['sometimes', 'nullable'],
            'type_filter' => ['sometimes', 'nullable'],
            'format_filter' => ['sometimes', 'nullable'],
            'missing_field' => ['sometimes', 'nullable'],
            'active' => ['sometimes', 'nullable'],
            'linked' => ['sometimes', 'nullable'],
            'sort_by' => ['sometimes', 'nullable'],
            'sort_order' => ['sometimes', 'nullable'],
            'has_isbn' => ['sometimes'],
            'url_unreachable' => ['sometimes'],
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
