<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\CronMutationInput;
use Illuminate\Validation\Rule;

final class CronMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'phase' => ['sometimes', 'nullable', 'string', Rule::in(['discover', 'scan'])],
            'cron_expression' => ['sometimes', 'nullable', 'string', 'max:100'],
            'chain_to_id' => ['sometimes', 'nullable', 'integer', 'min:1', 'exists:cron_jobs,id'],
            'clear_chain' => ['sometimes', 'boolean'],
            'strategy' => ['sometimes', 'nullable', 'string', 'max:100'],
        ];
    }

    public function toDto(): CronMutationInput
    {
        $this->validated();

        return new CronMutationInput(
            shop: $this->string('shop')->toString(),
            phase: $this->filled('phase') ? $this->string('phase')->toString() : null,
            cronExpression: $this->filled('cron_expression')
                ? $this->string('cron_expression')->toString()
                : null,
            chainToId: $this->filled('chain_to_id') ? $this->integer('chain_to_id') : null,
            clearChain: $this->boolean('clear_chain'),
            strategy: $this->filled('strategy')
                ? $this->string('strategy')->toString()
                : null,
        );
    }
}
