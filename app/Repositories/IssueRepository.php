<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ValidationIssue;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Support\Carbon;

final readonly class IssueRepository
{
    public function __construct(private DatabaseManager $database) {}

    public function setLifecycle(ValidationIssue $issue, string $state): void
    {
        $this->connection()->table('validation_issues')->where('id', $issue->getKey())->update([
            'lifecycle_state' => $state,
            'acknowledged_at' => $state === 'acknowledged' ? Carbon::now('UTC') : null,
        ]);
    }

    public function snooze(ValidationIssue $issue, Carbon $until): void
    {
        $this->connection()->table('validation_issues')->where('id', $issue->getKey())->update([
            'lifecycle_state' => 'snoozed',
            'snoozed_until' => $until,
        ]);
    }

    public function shopIdByName(string $name): ?int
    {
        $id = $this->connection()->table('shops')->where('name', $name)->value('id');

        return DatabaseRow::from(['id' => $id])->nullableInt('id');
    }

    public function bulkSetLifecycle(
        string $issueType,
        string $from,
        string $to,
        ?int $shopId,
    ): int {
        $query = $this->connection()->table('validation_issues')
            ->where('issue', $issueType)
            ->where('lifecycle_state', $from);

        if ($shopId !== null) {
            $query->where('shop_id', $shopId);
        }

        return $query->update([
            'lifecycle_state' => $to,
            'acknowledged_at' => $to === 'acknowledged' ? Carbon::now('UTC') : null,
        ]);
    }

    /** @return list<string> */
    public function productUrls(string $issueType, int $shopId): array
    {
        $values = $this->connection()->table('discovered_urls as du')
            ->join('shop_books as sb', 'sb.id', '=', 'du.shop_book_id')
            ->join('validation_issues as vi', 'vi.shop_book_id', '=', 'sb.id')
            ->where('du.url_type', 'product')
            ->where('vi.shop_id', $shopId)
            ->where('vi.issue', $issueType)
            ->whereIn('vi.lifecycle_state', ['new', 'acknowledged'])
            ->distinct()
            ->orderBy('du.url')
            ->pluck('du.url')
            ->filter()
            ->values()
            ->all();

        $urls = [];
        foreach ($values as $value) {
            if (is_string($value)) {
                $urls[] = $value;
            }
        }

        return $urls;
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
