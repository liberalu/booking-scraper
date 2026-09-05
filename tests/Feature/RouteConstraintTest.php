<?php

declare(strict_types=1);

namespace Tests\Feature;

use Tests\TestCase;

final class RouteConstraintTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        config(['dashboard.authentication_disabled' => true]);
    }

    public function test_non_numeric_resource_id_is_a_json_404(): void
    {
        $this->getJson('/api/books/not-a-number')
            ->assertNotFound()
            ->assertExactJson(['detail' => 'Not found']);
    }

    public function test_unknown_api_route_is_not_reported_as_an_unported_python_action(): void
    {
        $response = $this->postJson('/api/no-such-action');

        $response->assertMethodNotAllowed();
        self::assertStringNotContainsString('Python dashboard', (string) $response->getContent());
    }
}
