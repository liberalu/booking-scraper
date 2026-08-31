<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Models\Shop;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;

final readonly class CronJobRepository
{
    public function __construct(private DatabaseManager $database) {}

    public function shopByName(string $name): ?Shop
    {
        return Shop::where('name', $name)->first();
    }

    public function find(int $id): ?CronJob
    {
        return CronJob::find($id);
    }

    public function create(
        Shop $shop,
        string $phase,
        ?string $strategy,
        string $expression,
        ?int $chainToId,
    ): CronJob {
        $job = new CronJob;
        $job->shop_id = $shop->id;
        $job->phase = $phase;
        $job->strategy = $strategy;
        $job->args = '';
        $job->cron_expression = $expression;
        $job->enabled = true;
        $job->chain_to_job_id = $chainToId;
        $job->save();

        return $job;
    }

    /** @param array<string, bool|int|string|null> $fields */
    public function update(CronJob $job, array $fields): void
    {
        CronJob::whereKey($job->getKey())->update($fields);
    }

    public function delete(CronJob $job): void
    {
        CronJob::whereKey($job->getKey())->delete();
    }

    /** @return list<array<string, mixed>> */
    public function dependents(CronJob $job): array
    {
        $rows = $this->connection()->table('cron_jobs as cj')
            ->join('shops as s', 's.id', '=', 'cj.shop_id')
            ->where('cj.chain_to_job_id', $job->getKey())
            ->get(['cj.id', 'cj.phase', 'cj.strategy', 's.name'])
            ->all();

        $dependents = [];
        foreach ($rows as $dependent) {
            $row = DatabaseRow::from($dependent);
            $strategy = $row->nullableString('strategy');
            $dependents[] = [
                'id' => $row->int('id'),
                'name' => $row->string('name').'.'.$row->string('phase').'.'.($strategy ?? 'default'),
            ];
        }

        return $dependents;
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
