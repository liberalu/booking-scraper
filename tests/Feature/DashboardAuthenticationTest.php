<?php

declare(strict_types=1);

namespace Tests\Feature;

use Symfony\Component\HttpFoundation\Response;
use Tests\TestCase;

final class DashboardAuthenticationTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        config([
            'dashboard.username' => 'operator',
            'dashboard.password' => 'secret',
        ]);
    }

    public function test_api_requests_require_credentials(): void
    {
        $this->getJson('/api/overview')
            ->assertStatus(Response::HTTP_UNAUTHORIZED)
            ->assertHeader('WWW-Authenticate')
            ->assertExactJson(['detail' => 'Authentication required']);
    }

    public function test_web_requests_require_credentials(): void
    {
        $this->get('/validation')
            ->assertStatus(Response::HTTP_UNAUTHORIZED)
            ->assertHeader('WWW-Authenticate');
    }

    public function test_valid_credentials_reach_the_route(): void
    {
        $credentials = base64_encode('operator:secret');

        $this->withHeader('Authorization', "Basic {$credentials}")
            ->get('/validation')
            ->assertMovedPermanently()
            ->assertRedirect('/issues');
    }
}
