<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\PriceQueryInput;

final class PriceQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'days' => ['sometimes', 'nullable', 'integer', 'between:1,3650'],
            'page' => ['sometimes', 'nullable', 'integer', 'min:1', 'max:100000'],
            'per_page' => ['sometimes', 'nullable', 'integer', 'between:1,200'],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
        ];
    }

    public function toDto(): PriceQueryInput
    {
        $this->validated();

        return new PriceQueryInput(
            days: max(1, $this->integer('days', 7)),
            page: max(1, $this->integer('page', 1)),
            perPage: max(1, min($this->integer('per_page', 30), 200)),
            shop: $this->string('shop')->toString(),
        );
    }
}
