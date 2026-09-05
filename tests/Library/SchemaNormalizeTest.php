<?php

declare(strict_types=1);

namespace Tests\Library;

use PHPUnit\Framework\TestCase;

final class SchemaNormalizeTest extends TestCase
{
    private const string AS_EMITTED =
        '    CONSTRAINT ck_scrape_run_events_event_type CHECK (((event_type)::text = ANY '
        ."((ARRAY['started'::character varying, 'failed'::character varying])::text[])))";

    private const string AS_REDEPARSED =
        '    CONSTRAINT ck_scrape_run_events_event_type CHECK (((event_type)::text = ANY '
        ."(ARRAY[('started'::character varying)::text, ('failed'::character varying)::text])))";

    public function test_the_two_deparsings_of_one_check_converge(): void
    {
        self::assertSame(
            $this->normalize(self::AS_EMITTED),
            $this->normalize(self::AS_REDEPARSED),
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

        self::assertNotSame($this->normalize(self::AS_EMITTED), $this->normalize($extraValue));
    }

    public function test_a_changed_element_type_still_differs(): void
    {
        $retyped = str_replace('character varying', 'text', self::AS_EMITTED);

        self::assertNotSame($this->normalize(self::AS_EMITTED), $this->normalize($retyped));
    }

    public function test_a_changed_array_cast_still_differs(): void
    {
        $retyped = str_replace('::text[]', '::character varying[]', self::AS_EMITTED);

        self::assertNotSame($this->normalize(self::AS_EMITTED), $this->normalize($retyped));
    }

    public function test_an_unrelated_column_cast_is_left_alone(): void
    {
        $line = "CONSTRAINT ck_x CHECK (((a)::text <> ''::text))";

        self::assertSame($line, $this->normalize($line));
    }

    public function test_psql_meta_commands_are_dropped(): void
    {
        $dump = "\\restrict abc123\nCREATE TABLE public.t (id integer);\n\\unrestrict abc123\n";

        self::assertSame('CREATE TABLE public.t (id integer);', $this->normalize($dump));
    }

    public function test_the_pg_dump_version_header_is_dropped(): void
    {
        $dump = "-- Dumped by pg_dump version 16.13 (Debian)\nCREATE TABLE public.t (id integer);";

        self::assertSame('CREATE TABLE public.t (id integer);', $this->normalize($dump));
    }

    private function normalize(string $input): string
    {
        $script = dirname(__DIR__, 2).'/tools/schema_normalize.sh';
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
