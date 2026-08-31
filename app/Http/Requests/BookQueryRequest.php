<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\BookQueryInput;

final class BookQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'page' => ['sometimes', 'integer'],
            'per_page' => ['sometimes', 'integer'],
            'year' => ['sometimes', 'nullable', 'integer'],
            'shop_count_min' => ['sometimes', 'nullable', 'integer'],
            'shop_count_max' => ['sometimes', 'nullable', 'integer'],
            'has_isbn' => ['sometimes'],
            'has_shops' => ['sometimes'],
            'has_conflicts' => ['sometimes'],
            'data_source' => ['sometimes', 'nullable', 'string'],
            'search' => ['sometimes', 'nullable', 'string'],
            'format' => ['sometimes', 'nullable', 'string'],
        ];
    }

    public function toDto(): BookQueryInput
    {
        $this->validated();

        return new BookQueryInput(
            page: max(1, $this->integer('page', 1)),
            perPage: max(1, min($this->integer('per_page', 50), 200)),
            year: $this->filled('year') ? $this->integer('year') : null,
            shopCountMin: $this->filled('shop_count_min')
                ? $this->integer('shop_count_min')
                : null,
            shopCountMax: $this->filled('shop_count_max')
                ? $this->integer('shop_count_max')
                : null,
            hasIsbn: $this->exists('has_isbn') ? $this->boolean('has_isbn') : null,
            hasShops: $this->exists('has_shops') ? $this->boolean('has_shops') : null,
            hasConflicts: $this->exists('has_conflicts') ? $this->boolean('has_conflicts') : null,
            dataSource: $this->exists('data_source')
                ? $this->string('data_source')->toString()
                : null,
            search: trim($this->string('search')->toString()),
            format: $this->exists('format') ? $this->string('format')->toString() : null,
        );
    }
}
