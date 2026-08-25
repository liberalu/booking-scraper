<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use PHPUnit\Framework\TestCase;

/**
 * The schema gate's honesty rests entirely on `tools/schema_normalize.sh`.
 *
 * It has to fold together the one CHECK expression Postgres deparses two
 * equivalent ways — otherwise the gate reports a permanent false positive and
 * gets ignored — while still failing on a difference that matters. A blanket
 * "strip anything cast-shaped" would do the first and not the second, so both
 * directions are pinned here.
 */
final class SchemaNormalizeTest extends TestCase
{
    /** As SQLAlchemy emits it: the array cast outside the constructor. */
    private const AS_EMITTED =
        "    CONSTRAINT ck_scrape_run_events_event_type CHECK (((event_type)::text = ANY "
        . "((ARRAY['started'::character varying, 'failed'::character varying])::text[])))";

    /** As Postgres re-renders it once the constraint has survived a restore. */
    private const AS_REDEPARSED =
        "    CONSTRAINT ck_scrape_run_events_event_type CHECK (((event_type)::text = ANY "
        . "(ARRAY[('started'::character varying)::text, ('failed'::character varying)::text])))";

    public function test_the_two_deparsings_of_one_check_converge(): void
    {
        self::assertSame(
            self::normalize(self::AS_EMITTED),
            self::normalize(self::AS_REDEPARSED),
            'the gate would report a permanent false positive'
        );
    }

    public function test_a_changed_value_still_differs(): void
    {
        $extraValue = str_replace(
            "'failed'::character varying",
            "'failed'::character varying, 'reaped'::character varying",
            self::AS_REDEPARSED
        );

        self::assertNotSame(self::normalize(self::AS_EMITTED), self::normalize($extraValue));
    }

    public function test_a_changed_element_type_still_differs(): void
    {
        $retyped = str_replace('character varying', 'text', self::AS_EMITTED);

        self::assertNotSame(self::normalize(self::AS_EMITTED), self::normalize($retyped));
    }

    public function test_a_changed_array_cast_still_differs(): void
    {
        $retyped = str_replace('::text[]', '::character varying[]', self::AS_EMITTED);

        self::assertNotSame(self::normalize(self::AS_EMITTED), self::normalize($retyped));
    }

    /** An unrelated cast is not a normalisation target. */
    public function test_an_unrelated_column_cast_is_left_alone(): void
    {
        $line = "CONSTRAINT ck_x CHECK (((a)::text <> ''::text))";

        self::assertSame($line, self::normalize($line));
    }

    public function test_psql_meta_commands_are_dropped(): void
    {
        $dump = "\\restrict abc123\nCREATE TABLE public.t (id integer);\n\\unrestrict abc123\n";

        self::assertSame("CREATE TABLE public.t (id integer);", self::normalize($dump));
    }

    public function test_the_pg_dump_version_header_is_dropped(): void
    {
        $dump = "-- Dumped by pg_dump version 16.13 (Debian)\nCREATE TABLE public.t (id integer);";

        self::assertSame("CREATE TABLE public.t (id integer);", self::normalize($dump));
    }

    private static function normalize(string $input): string
    {
        $script = dirname(__DIR__) . '/tools/schema_normalize.sh';
        $descriptors = [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
        $process = proc_open(['/bin/bash', $script], $descriptors, $pipes);
        self::assertIsResource($process);

        fwrite($pipes[0], $input);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $status = proc_close($process);

        self::assertSame(0, $status, "schema_normalize.sh failed: {$stderr}");

        return trim($stdout);
    }
}
