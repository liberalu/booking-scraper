<?php

declare(strict_types=1);

namespace App\Http\Requests;

use App\DTO\Request\RunMutationInput;
use App\Support\Config;
use App\Support\CrawlerUrlPolicy;
use Closure;
use Illuminate\Validation\Rule;
use Throwable;

final class RunMutationRequest extends ApiFormRequest
{
    /** @return array<string, list<mixed>> */
    public function rules(): array
    {
        return [
            'phase' => ['sometimes', 'nullable', 'string', Rule::in(['discover', 'scan', 'match', 'validate'])],
            'shop' => ['sometimes', 'nullable', 'string', 'max:100', 'exists:shops,name'],
            'strategy' => ['sometimes', 'nullable', 'string', 'max:100'],
            'mode' => ['sometimes', 'nullable', 'string', Rule::in(['delta', 'full', 'sample'])],
            'urls' => ['sometimes', 'nullable', 'string', 'max:1000000', $this->validUrls(...)],
            'cron_job_id' => ['sometimes', 'nullable', 'integer', 'min:1', 'exists:cron_jobs,id'],
            'error_reason' => ['sometimes', 'nullable', 'string', 'max:500'],
            'error_reason_is_null' => ['sometimes', 'boolean'],
            'http_status' => ['sometimes', 'nullable', 'integer', 'between:100,599'],
            'http_status_is_null' => ['sometimes', 'boolean'],
            'note' => ['sometimes', 'nullable', 'string', 'max:1000'],
        ];
    }

    private function validUrls(string $attribute, mixed $value, Closure $fail): void
    {
        if (! is_string($value) || trim($value) === '') {
            return;
        }

        $shop = $this->input('shop');
        if (! is_string($shop) || $shop === '') {
            $fail('A shop is required when explicit URLs are supplied.');

            return;
        }

        try {
            CrawlerUrlPolicy::parse($value, Config::forShop($shop)->baseUrl());
        } catch (Throwable $exception) {
            $fail($exception->getMessage());
        }
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
