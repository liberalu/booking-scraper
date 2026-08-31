<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\IssueMutationInput;

final class IssueMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'state' => ['sometimes', 'nullable'],
            'days' => ['sometimes', 'nullable'],
            'issue_type' => ['sometimes', 'nullable'],
            'shop' => ['sometimes', 'nullable'],
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
