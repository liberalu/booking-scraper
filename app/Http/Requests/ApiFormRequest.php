<?php

declare(strict_types=1);

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

abstract class ApiFormRequest extends FormRequest
{
    private const array BOOLEAN_INPUTS = [
        'clear_chain',
        'error_reason_is_null',
        'failing',
        'has_book',
        'has_conflicts',
        'has_isbn',
        'has_shops',
        'http_status_is_null',
        'include_acked',
        'url_unreachable',
    ];

    public function authorize(): bool
    {
        return true;
    }

    protected function prepareForValidation(): void
    {
        foreach (self::BOOLEAN_INPUTS as $key) {
            if (! $this->has($key) || ! is_string($this->input($key))) {
                continue;
            }

            $value = match (strtolower($this->string($key)->toString())) {
                '1', 'true', 'on', 'yes' => true,
                '0', 'false', 'off', 'no' => false,
                default => $this->input($key),
            };
            $this->merge([$key => $value]);
        }
    }
}
