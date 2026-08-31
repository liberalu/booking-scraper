<?php

declare(strict_types=1);

namespace App\Exceptions;

enum FailureKind
{
    case BadRequest;
    case Conflict;
    case NotFound;
    case PayloadTooLarge;
    case Unavailable;
    case Unprocessable;
}
