<?php

declare(strict_types=1);

namespace App\Support;

final class Queries
{
    public static function pageCount(int $total, int $perPage): int
    {
        return $total > 0 ? max(1, intdiv($total + $perPage - 1, $perPage)) : 1;
    }
}
