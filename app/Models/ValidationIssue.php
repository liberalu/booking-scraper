<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/** @property int $id */
final class ValidationIssue extends Model
{
    protected $table = 'validation_issues';

    public $timestamps = false;
}
