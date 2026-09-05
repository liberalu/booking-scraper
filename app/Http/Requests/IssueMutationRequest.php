<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\IssueMutationInput;
use Illuminate\Validation\Rule;

final class IssueMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'state' => ['sometimes', 'nullable', 'string', Rule::in(['new', 'acknowledged', 'snoozed', 'resolved'])],
            'days' => ['sometimes', 'nullable', 'integer', 'between:1,3650'],
            'issue_type' => ['sometimes', 'nullable', 'string', 'max:200'],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
        ];
    }

    public function toDto(): IssueMutationInput
    {
        $this->validated();

        return new IssueMutationInput(
            state: $this->string('state')->toString(),
            days: $this->integer('days') !== 0 ? $this->integer('days') : 7,
            issueType: $this->string('issue_type')->toString(),
            shop: $this->string('shop')->toString(),
        );
    }
}
