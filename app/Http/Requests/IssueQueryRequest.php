<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\IssueQueryInput;

final class IssueQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'state' => ['sometimes', 'nullable'],
            'shop' => ['sometimes', 'nullable'],
            'issue_type' => ['sometimes', 'nullable'],
            'run_id' => ['sometimes', 'nullable'],
            'severity' => ['sometimes', 'nullable'],
            'url_type' => ['sometimes', 'nullable'],
            'book_type' => ['sometimes', 'nullable'],
            'q' => ['sometimes', 'nullable'],
            'sort_by' => ['sometimes', 'nullable'],
            'order' => ['sometimes', 'nullable'],
            'page' => ['sometimes', 'nullable'],
            'per_page' => ['sometimes', 'nullable'],
            'kind' => ['sometimes', 'nullable'],
            'group_by' => ['sometimes', 'nullable'],
            'days' => ['sometimes', 'nullable'],
        ];
    }

    public function toDto(): IssueQueryInput
    {
        $this->validated();

        return new IssueQueryInput(
            state: $this->filled('state') ? $this->string('state')->toString() : null,
            shop: $this->string('shop')->toString(),
            issueType: $this->string('issue_type')->toString(),
            runId: $this->integer('run_id') !== 0 ? $this->integer('run_id') : null,
            severity: $this->string('severity')->toString(),
            urlType: $this->filled('url_type') ? $this->string('url_type')->toString() : null,
            bookType: $this->filled('book_type') ? $this->string('book_type')->toString() : null,
            search: $this->string('q')->toString(),
            sortBy: $this->filled('sort_by') ? $this->string('sort_by')->toString() : null,
            order: $this->filled('order') ? $this->string('order')->toString() : null,
            page: $this->filled('page') ? $this->integer('page') : null,
            perPage: $this->filled('per_page') ? $this->integer('per_page') : null,
            kind: $this->filled('kind') ? $this->string('kind')->toString() : null,
            groupBy: $this->filled('group_by') ? $this->string('group_by')->toString() : null,
            days: $this->filled('days') ? $this->integer('days') : null,
        );
    }
}
