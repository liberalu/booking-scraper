<?php

declare(strict_types=1);

namespace Tests\Unit;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;

final class ControllerArchitectureTest extends TestCase
{
    public function test_api_controllers_remain_thin_adapters(): void
    {
        $files = glob(__DIR__.'/../../app/Http/Controllers/Api/*Controller.php') ?: [];

        self::assertNotEmpty($files);

        foreach ($files as $file) {
            $source = (string) file_get_contents($file);
            $name = basename($file);

            self::assertLessThanOrEqual(80, substr_count($source, "\n") + 1, $name);
            self::assertStringNotContainsString('extends Controller', $source, $name);
            self::assertStringNotContainsString('Illuminate\\Support\\Facades\\', $source, $name);
            self::assertStringNotContainsString('DB::', $source, $name);
            self::assertTrue(
                str_contains($source, 'App\\Services\\') || str_contains($source, 'App\\Queries\\'),
                $name,
            );
        }
    }

    public function test_services_are_framework_neutral_business_components(): void
    {
        $files = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator(__DIR__.'/../../app/Services'),
        );

        foreach ($files as $file) {
            if (! $file->isFile() || $file->getExtension() !== 'php') {
                continue;
            }

            $source = (string) file_get_contents($file->getPathname());
            $name = $file->getFilename();

            self::assertStringNotContainsString(Request::class, $source, $name);
            self::assertStringNotContainsString('Illuminate\\Database\\', $source, $name);
            self::assertStringNotContainsString(DB::class, $source, $name);
            self::assertStringNotContainsString('DTO\\Response', $source, $name);
            self::assertStringNotContainsString('::query()', $source, $name);
            self::assertStringNotContainsString('::where(', $source, $name);
            self::assertStringNotContainsString('::find(', $source, $name);
            self::assertStringNotContainsString('response()', $source, $name);
            self::assertStringNotContainsString('redirect()', $source, $name);
        }
    }

    public function test_api_queries_delegate_database_access_to_repositories(): void
    {
        $files = glob(__DIR__.'/../../app/Queries/Api/*.php') ?: [];

        self::assertNotEmpty($files);

        foreach ($files as $file) {
            $source = (string) file_get_contents($file);
            $name = basename($file);

            self::assertStringContainsString('App\\Repositories\\', $source, $name);
            self::assertStringNotContainsString('Illuminate\\Database', $source, $name);
            self::assertStringNotContainsString('Facades\\DB', $source, $name);
            self::assertStringNotContainsString('DB::', $source, $name);
            self::assertStringNotContainsString('::query()', $source, $name);
            self::assertStringNotContainsString('::where(', $source, $name);
            self::assertStringNotContainsString('::find(', $source, $name);
        }
    }

    public function test_form_requests_are_the_only_request_to_dto_boundary(): void
    {
        $requests = glob(__DIR__.'/../../app/Http/Requests/*Request.php') ?: [];

        self::assertNotEmpty($requests);

        foreach ($requests as $file) {
            $source = (string) file_get_contents($file);
            $name = basename($file);

            if ($name !== 'ApiFormRequest.php') {
                self::assertStringContainsString('function toDto():', $source, $name);
            }

            self::assertStringNotContainsString('bodyInput()', $source, $name);
            self::assertStringNotContainsString('queryInput()', $source, $name);
        }

        $sourceFiles = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator(__DIR__.'/../../app'),
        );

        foreach ($sourceFiles as $file) {
            if (! $file->isFile() || $file->getExtension() !== 'php') {
                continue;
            }

            $source = (string) file_get_contents($file->getPathname());
            self::assertStringNotContainsString(
                'App\\DTO\\Request\\QueryInput',
                $source,
                $file->getFilename(),
            );
        }
    }

    public function test_runtime_database_access_is_isolated_in_repositories(): void
    {
        $files = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator(__DIR__.'/../../app'),
        );

        foreach ($files as $file) {
            if (! $file->isFile() || $file->getExtension() !== 'php') {
                continue;
            }

            $path = $file->getPathname();
            if ($this->isDatabaseInfrastructure($path)) {
                continue;
            }

            $source = (string) file_get_contents($path);
            $name = $file->getFilename();

            if ($name !== 'AppServiceProvider.php') {
                self::assertStringNotContainsString('Illuminate\\Database\\', $source, $name);
            }
            self::assertStringNotContainsString('Facades\\DB', $source, $name);
            self::assertStringNotContainsString('DB::', $source, $name);
            self::assertStringNotContainsString('use PDO;', $source, $name);
            self::assertStringNotContainsString('->prepare(', $source, $name);
            self::assertDoesNotMatchRegularExpression(
                '/\\b(?:Book|BookIsbn|CronJob|DiscoveredUrl|Price|ScrapeRun|ScrapeUrlItem|Shop|ShopAuthor|ShopBook|ShopBookAttribute|UrlClassification|ValidationIssue)::(?:query|where|whereKey|whereIn|find|findOrFail|with|create|count)\\b/',
                $source,
                $name,
            );
        }

        foreach (glob(__DIR__.'/../../bin/*') ?: [] as $path) {
            if (! is_file($path)) {
                continue;
            }

            $source = (string) file_get_contents($path);
            $name = basename($path);

            self::assertStringNotContainsString('Facades\\DB', $source, $name);
            self::assertStringNotContainsString('DB::', $source, $name);
        }
    }

    public function test_models_do_not_own_persistence_operations(): void
    {
        foreach (glob(__DIR__.'/../../app/Models/*.php') ?: [] as $path) {
            $source = (string) file_get_contents($path);
            $name = basename($path);

            self::assertDoesNotMatchRegularExpression(
                '/(?:::create|::where|::whereKey|->save|->update|->delete)\\s*\\(/',
                $source,
                $name,
            );
        }
    }

    private function isDatabaseInfrastructure(string $path): bool
    {
        return str_contains($path, '/Repositories/')
            || str_contains($path, '/Models/')
            || str_contains($path, '/Casts/')
            || str_contains($path, '/Schema/')
            || str_ends_with($path, '/Support/Database.php');
    }
}
