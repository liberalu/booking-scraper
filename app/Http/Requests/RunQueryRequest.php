<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\RunQueryInput;

final class RunQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'shop' => ['sometimes', 'nullable'],
            'phase' => ['sometimes', 'nullable'],
            'status' => ['sometimes', 'nullable'],
            'when' => ['sometimes', 'nullable'],
            'q' => ['sometimes', 'nullable'],
            'page' => ['sometimes', 'nullable'],
            'per_page' => ['sometimes', 'nullable'],
            'type' => ['sometimes', 'nullable'],
            'sort' => ['sometimes', 'nullable'],
            'order' => ['sometimes', 'nullable'],
            'error_reason' => ['sometimes', 'nullable'],
            'error_reason_is_null' => ['sometimes'],
            'http_status' => ['sometimes', 'nullable'],
            'http_status_is_null' => ['sometimes'],
            'include_acked' => ['sometimes'],
            'note' => ['sometimes', 'nullable'],
        ];
    }

    public function toDto(): RunQueryInput
    {
        $this->validated();

        return new RunQueryInput(
            shop: $this->filled('shop') ? $this->string('shop')->toString() : null,
            phase: $this->filled('phase') ? $this->string('phase')->toString() : null,
            status: $this->filled('status') ? $this->string('status')->toString() : null,
            when: $this->filled('when') ? $this->string('when')->toString() : null,
            search: trim($this->string('q')->toString()),
            page: $this->filled('page') ? $this->integer('page') : null,
            perPage: $this->filled('per_page') ? $this->integer('per_page') : null,
            type: $this->filled('type') ? $this->string('type')->toString() : null,
            sort: $this->filled('sort') ? $this->string('sort')->toString() : null,
            order: $this->filled('order') ? $this->string('order')->toString() : null,
            errorReason: $this->string('error_reason')->toString(),
            errorReasonIsNull: $this->boolean('error_reason_is_null'),
            httpStatus: $this->filled('http_status') ? $this->integer('http_status') : null,
            httpStatusIsNull: $this->boolean('http_status_is_null'),
            includeAcknowledged: $this->boolean('include_acked'),
            note: $this->string('note')->toString(),
        );
    }
}
