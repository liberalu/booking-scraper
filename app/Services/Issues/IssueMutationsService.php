<?php

declare(strict_types=1);

namespace App\Services\Issues;

use App\DTO\Request\IssueMutationInput;
use App\Exceptions\ActionFailed;
use App\Models\ValidationIssue;
use App\Repositories\IssueRepository;
use Illuminate\Support\Carbon;

final readonly class IssueMutationsService
{
    private const array LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    private const array SNOOZE_DAYS = [7, 30, 90];

    public function __construct(private IssueRepository $issues) {}

    /** @return array{id: int, lifecycle_state: string} */
    public function lifecycle(IssueMutationInput $input, ValidationIssue $issue): array
    {
        $state = $input->state;
        if (! in_array($state, self::LIFECYCLE_STATES, true)) {
            throw ActionFailed::badRequest([
                'detail' => "state must be one of {'".implode("', '", self::LIFECYCLE_STATES)."'}",
            ]);
        }

        $issueId = $issue->id;
        $this->issues->setLifecycle($issue, $state);

        return ['id' => $issueId, 'lifecycle_state' => $state];
    }

    /** @return array{snoozed_until: string, days: int} */
    public function snooze(IssueMutationInput $input, ValidationIssue $issue): array
    {
        $days = $input->days;
        if (! in_array($days, self::SNOOZE_DAYS, true)) {
            throw ActionFailed::unprocessable(['detail' => 'days must be 7, 30, or 90']);
        }

        $until = Carbon::now('UTC')->addDays($days);
        $this->issues->snooze($issue, $until);

        return ['snoozed_until' => $this->iso($until), 'days' => $days];
    }

    /** @return array{acknowledged: int} */
    public function bulkAcknowledge(IssueMutationInput $input): array
    {
        $issueType = $input->issueType;
        if ($issueType === '') {
            throw ActionFailed::unprocessable(['detail' => 'issue_type is required']);
        }

        $shopId = $this->shopId($input);

        return ['acknowledged' => $this->issues->bulkSetLifecycle(
            $issueType,
            'new',
            'acknowledged',
            $shopId,
        )];
    }

    /** @return array{unacknowledged: int} */
    public function bulkUnacknowledge(IssueMutationInput $input): array
    {
        $issueType = $input->issueType;
        if ($issueType === '') {
            throw ActionFailed::unprocessable(['detail' => 'issue_type is required']);
        }

        $shopId = $this->shopId($input);

        return ['unacknowledged' => $this->issues->bulkSetLifecycle(
            $issueType,
            'acknowledged',
            'new',
            $shopId,
        )];
    }

    /** @return array{urls: string, count: int} */
    public function bulkRescrape(IssueMutationInput $input): array
    {
        $issueType = $input->issueType;
        if ($issueType === '') {
            throw ActionFailed::unprocessable(['detail' => 'issue_type is required']);
        }
        $shopName = $input->shop;
        if ($shopName === '') {
            throw ActionFailed::unprocessable(['detail' => 'shop is required']);
        }
        $shopId = $this->issues->shopIdByName($shopName);
        if ($shopId === null) {
            throw ActionFailed::notFound(['detail' => "Unknown shop: {$shopName}"]);
        }

        $urls = $this->issues->productUrls($issueType, $shopId);

        return ['urls' => implode(',', $urls), 'count' => count($urls)];
    }

    private function shopId(IssueMutationInput $input): ?int
    {
        $name = $input->shop;
        if ($name === '') {
            return null;
        }
        $id = $this->issues->shopIdByName($name);

        if ($id === null) {
            throw ActionFailed::notFound(['detail' => "Unknown shop: {$name}"]);
        }

        return $id;
    }

    private function iso(Carbon $dt): string
    {
        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }
}
