<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\LegacyFormInput;

final class LegacyFormRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [];
    }

    public function toDto(): LegacyFormInput
    {
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
