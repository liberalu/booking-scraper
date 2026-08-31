<?php

declare(strict_types=1);

namespace App\DTO;

enum LegacyActionKind
{
    case Accepted;
    case Html;
    case Redirect;
}
