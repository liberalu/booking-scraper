<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\Markdown;
use PHPUnit\Framework\TestCase;

final class MarkdownTest extends TestCase
{
    private function golden(): array
    {
        $path = __DIR__.'/../golden/descriptions.json';
        self::assertFileExists($path, 'run `make markdown-golden` first');

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }

    public function test_every_description_converts_as_markdownify_does(): void
    {
        $checked = 0;
        foreach ($this->golden() as $case) {
            self::assertSame(
                $case['markdown'],
                Markdown::fromHtml($case['html']),
                "description conversion: {$case['label']}"
            );
            $checked++;
        }

        self::assertGreaterThanOrEqual(30, $checked);
    }

    public function test_a_break_after_a_break_keeps_the_rest_of_the_paragraph(): void
    {

        self::assertSame(
            "One  \nTwo  \nThree",
            Markdown::fromHtml('<p>One<br>Two<br/>Three</p>')
        );
    }

    public function test_non_breaking_space_is_kept_inside_text_and_trimmed_at_edges(): void
    {
        self::assertSame("matę \u{00A0}Alano", Markdown::fromHtml("<p>matę \u{00A0}Alano</p>"));
        self::assertSame('klydo.', Markdown::fromHtml("<p>klydo.\u{00A0}</p>"));
        self::assertNull(Markdown::fromHtml("<p>\u{00A0}</p>"));
    }

    public function test_a_break_shields_a_trailing_non_breaking_space(): void
    {
        self::assertSame("a.\u{00A0}\n\nb", Markdown::fromHtml("<p>a.\u{00A0}<br></p><p>b</p>"));
        self::assertSame("a.\n\nb", Markdown::fromHtml("<p>a.\u{00A0}</p><p>b</p>"));
        self::assertSame("a.\n\nb", Markdown::fromHtml('<p>a.<br></p><p>b</p>'));
    }

    public function test_literal_angle_brackets_survive(): void
    {
        self::assertSame('komodos. <...> Reikia', Markdown::fromHtml('<p>komodos. <...> Reikia</p>'));
    }

    public function test_plain_text_and_empty_input_pass_straight_through(): void
    {
        self::assertSame('just words', Markdown::fromHtml('just words'));
        self::assertNull(Markdown::fromHtml(null));
        self::assertNull(Markdown::fromHtml('   '));
        self::assertNull(Markdown::fromHtml('<p></p>'));
    }
}
