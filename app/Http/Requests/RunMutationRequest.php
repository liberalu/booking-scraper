<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\RunMutationInput;

final class RunMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<string>> */
    public function rules(): array
    {
        return [
            'phase' => ['sometimes', 'nullable'],
            'shop' => ['sometimes', 'nullable'],
            'strategy' => ['sometimes', 'nullable'],
            'mode' => ['sometimes', 'nullable'],
            'urls' => ['sometimes', 'nullable'],
            'cron_job_id' => ['sometimes', 'nullable'],
            'error_reason' => ['sometimes', 'nullable'],
            'error_reason_is_null' => ['sometimes'],
            'http_status' => ['sometimes', 'nullable'],
            'http_status_is_null' => ['sometimes'],
            'note' => ['sometimes', 'nullable'],
        ];
    }

    public function toDto(): RunMutationInput
    {
        $this->validated();

        return new RunMutationInput(
            phase: $this->filled('phase') ? $this->string('phase')->toString() : 'scan',
            shop: $this->string('shop')->toString(),
            strategy: $this->string('strategy')->toString(),
            mode: $this->filled('mode') ? $this->string('mode')->toString() : 'delta',
            urls: $this->string('urls')->toString(),
            cronJobId: $this->filled('cron_job_id') ? $this->integer('cron_job_id') : null,
            errorReason: $this->string('error_reason')->toString(),
            errorReasonIsNull: $this->boolean('error_reason_is_null'),
            httpStatus: $this->filled('http_status') ? $this->integer('http_status') : null,
            httpStatusIsNull: $this->boolean('http_status_is_null'),
            note: $this->string('note')->toString(),
        );
    }
}
