<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\Database;

final class DatabaseRepositoryFactory
{
    public function matching(): MatchingRepository
    {
        return new MatchingRepository(Database::manager());
    }

    public function validation(): ValidationRepository
    {
        $database = Database::manager();

        return new ValidationRepository(new ValidationIssueRepository($database), $database);
    }
}
