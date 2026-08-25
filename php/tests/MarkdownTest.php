<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Markdown;
use PHPUnit\Framework\TestCase;

/**
 * The description column stores Markdown, converted from scraped HTML by the
 * Python validation pipeline. Production holds zero HTML descriptions, so this
 * conversion is not optional: storing the raw HTML would regress every book on
 * a dashboard that renders the column as Markdown.
 *
 * Held to markdownify's real output over the golden corpus. Regenerate with
 * `make markdown-golden`.
 */
final class MarkdownTest extends TestCase
{
    /** @return list<array{label: string, html: string, markdown: string}> */
    private static function golden(): array
    {
        $path = __DIR__ . '/golden/descriptions.json';
        self::assertFileExists($path, 'run `make markdown-golden` first');

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }

    public function testEveryDescriptionConvertsAsMarkdownifyDoes(): void
    {
        $checked = 0;
        foreach (self::golden() as $case) {
            self::assertSame(
                $case['markdown'],
                Markdown::fromHtml($case['html']),
                "description conversion: {$case['label']}"
            );
            $checked++;
        }
        // A shrinking corpus would make this test pass by doing nothing. No
        // case is skipped any more: the one deliberate divergence was the
        // markdownify `<br/>` truncation, and upstream now normalises it.
        self::assertGreaterThanOrEqual(30, $checked);
    }

    public function testABreakAfterABreakKeepsTheRestOfTheParagraph(): void
    {
        // markdownify used to drop everything after a `<br/>` that followed a
        // `<br>` in one paragraph — an html.parser artifact that silently lost
        // content. This port never reproduced it; upstream now normalises the
        // self-closing form before converting, so both keep the text.
        self::assertSame(
            "One  \nTwo  \nThree",
            Markdown::fromHtml('<p>One<br>Two<br/>Three</p>')
        );
    }

    /** A non-breaking space is typography inside a sentence, padding at an edge. */
    public function testNonBreakingSpaceIsKeptInsideTextAndTrimmedAtEdges(): void
    {
        self::assertSame("matę \u{00A0}Alano", Markdown::fromHtml("<p>matę \u{00A0}Alano</p>"));
        self::assertSame('klydo.', Markdown::fromHtml("<p>klydo.\u{00A0}</p>"));
        self::assertNull(Markdown::fromHtml("<p>\u{00A0}</p>"));
    }

    /**
     * A `<br>` at the end of a paragraph shields a U+00A0 in front of it from
     * the edge trim. Shops emit `…&nbsp;<br></p>` constantly, so this decides
     * the stored text of a large share of descriptions — it is not a curiosity.
     */
    public function testABreakShieldsATrailingNonBreakingSpace(): void
    {
        self::assertSame("a.\u{00A0}\n\nb", Markdown::fromHtml("<p>a.\u{00A0}<br></p><p>b</p>"));
        self::assertSame("a.\n\nb", Markdown::fromHtml("<p>a.\u{00A0}</p><p>b</p>"));
        self::assertSame("a.\n\nb", Markdown::fromHtml('<p>a.<br></p><p>b</p>'));
    }

    /** Literal angle brackets are content; libxml would eat them as markup. */
    public function testLiteralAngleBracketsSurvive(): void
    {
        self::assertSame('komodos. <...> Reikia', Markdown::fromHtml('<p>komodos. <...> Reikia</p>'));
    }

    public function testPlainTextAndEmptyInputPassStraightThrough(): void
    {
        self::assertSame('just words', Markdown::fromHtml('just words'));
        self::assertNull(Markdown::fromHtml(null));
        self::assertNull(Markdown::fromHtml('   '));
        self::assertNull(Markdown::fromHtml('<p></p>'));
    }
}
