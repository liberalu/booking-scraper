<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\IssueQueryInput;
use Illuminate\Validation\Rule;

final class IssueQueryRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'state' => ['sometimes', 'nullable', 'string', Rule::in(['all', 'open', 'new', 'acknowledged', 'snoozed', 'resolved'])],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'issue_type' => ['sometimes', 'nullable', 'string', 'max:200'],
            'run_id' => ['sometimes', 'nullable', 'integer', 'min:1', 'exists:scrape_runs,id'],
            'severity' => ['sometimes', 'nullable', 'string', Rule::in(['critical', 'warning', 'info'])],
            'url_type' => ['sometimes', 'nullable', 'string', 'max:100'],
            'book_type' => ['sometimes', 'nullable', 'string', 'max:100'],
            'q' => ['sometimes', 'nullable', 'string', 'max:500'],
            'sort_by' => ['sometimes', 'nullable', 'string', Rule::in(['id', 'age', 'type', 'shop', 'state', 'sev'])],
            'order' => ['sometimes', 'nullable', 'string', Rule::in(['asc', 'desc'])],
            'page' => ['sometimes', 'nullable', 'integer', 'min:1', 'max:100000'],
            'per_page' => ['sometimes', 'nullable', 'integer', 'between:1,200'],
            'kind' => ['sometimes', 'nullable', 'string', Rule::in(['all', 'validation', 'scrape_failure'])],
            'group_by' => ['sometimes', 'nullable', 'string', Rule::in(['type', 'type_shop'])],
            'days' => ['sometimes', 'nullable', 'integer', 'between:1,3650'],
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
