<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\RunQueryInput;
use Illuminate\Validation\Rule;

final class RunQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'phase' => ['sometimes', 'nullable', 'string', 'max:100'],
            'status' => ['sometimes', 'nullable', 'string', Rule::in([
                'all', 'running', 'paused', 'stopping', 'completed', 'failed',
                'pending', 'processing', 'done',
            ])],
            'when' => ['sometimes', 'nullable', 'string', Rule::in(['any', 'today', '24h', '7d', '30d'])],
            'q' => ['sometimes', 'nullable', 'string', 'max:500'],
            'page' => ['sometimes', 'nullable', 'integer', 'min:1', 'max:100000'],
            'per_page' => ['sometimes', 'nullable', 'integer', 'between:1,200'],
            'type' => ['sometimes', 'nullable', 'string', 'max:100'],
            'sort' => ['sometimes', 'nullable', 'string', 'max:100'],
            'order' => ['sometimes', 'nullable', 'string', Rule::in(['asc', 'desc'])],
            'error_reason' => ['sometimes', 'nullable', 'string', 'max:500'],
            'error_reason_is_null' => ['sometimes', 'boolean'],
            'http_status' => ['sometimes', 'nullable', 'integer', 'between:100,599'],
            'http_status_is_null' => ['sometimes', 'boolean'],
            'include_acked' => ['sometimes', 'boolean'],
            'note' => ['sometimes', 'nullable', 'string', 'max:1000'],
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
