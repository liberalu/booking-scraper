<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\LegacyFormInput;
use Illuminate\Validation\Rule;

final class LegacyFormRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'download_delay' => ['sometimes', 'numeric'],
            'concurrent_requests_per_domain' => ['sometimes', 'integer'],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'q' => ['sometimes', 'nullable', 'string', 'max:500'],
            'author' => ['sometimes', 'nullable', 'string', 'max:500'],
            'publisher' => ['sometimes', 'nullable', 'string', 'max:500'],
            'category' => ['sometimes', 'nullable', 'string', 'max:500'],
            'format' => ['sometimes', 'nullable', 'string', 'max:100'],
            'missing' => ['sometimes', 'nullable', 'string', Rule::in([
                'title', 'author', 'isbn', 'publisher', 'year', 'price', 'format', 'image_url',
            ])],
            'active' => ['sometimes', 'nullable', 'string', Rule::in(['true', 'false'])],
            'has_isbn' => ['sometimes', 'boolean'],
            'output' => ['sometimes', 'nullable', 'string', Rule::in(['json'])],
        ];
    }

    public function toDto(): LegacyFormInput
    {
        $this->validated();

        return new LegacyFormInput(
            downloadDelay: $this->float('download_delay'),
            concurrentRequestsPerDomain: $this->integer('concurrent_requests_per_domain'),
            shop: $this->string('shop')->toString(),
            search: $this->string('q')->toString(),
            author: $this->string('author')->toString(),
            publisher: $this->string('publisher')->toString(),
            category: $this->string('category')->toString(),
            format: $this->string('format')->toString(),
            missing: $this->string('missing')->toString(),
            active: $this->string('active')->toString(),
            hasIsbn: $this->boolean('has_isbn'),
            output: $this->string('output')->toString(),
        );
    }
}
