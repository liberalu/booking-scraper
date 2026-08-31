<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\CronMutationInput;

final class CronMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'shop' => ['sometimes', 'nullable'],
            'phase' => ['sometimes', 'nullable'],
            'cron_expression' => ['sometimes', 'nullable'],
            'chain_to_id' => ['sometimes', 'nullable'],
            'clear_chain' => ['sometimes'],
            'strategy' => ['sometimes', 'nullable'],
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
