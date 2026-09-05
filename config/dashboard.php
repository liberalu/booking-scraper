<?php

declare(strict_types=1);

return [
    'authentication_disabled' => env('DASHBOARD_AUTH_DISABLED', false),
    'username' => env('DASHBOARD_AUTH_USERNAME'),
    'password' => env('DASHBOARD_AUTH_PASSWORD'),
];
