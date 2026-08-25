<?php

declare(strict_types=1);

namespace BookScraper;

use DOMDocument;
use DOMElement;
use DOMNode;
use DOMText;

/**
 * HTML → Markdown for scraped descriptions.
 *
 * Not a general-purpose converter: it reproduces what
 * `markdownify(html, heading_style="ATX")` produces, because that is what the
 * Python validation pipeline stores and there are no HTML descriptions left in
 * production to fall back on. A port that saved the raw HTML would regress
 * every book on the dashboard, which renders the column as Markdown.
 *
 * Held to markdownify's actual output over a 25-case corpus of real and
 * synthetic descriptions (tests/golden/descriptions.json). One case diverges
 * deliberately — see BREAK_QUIRK below.
 */
final class Markdown
{
    /** Characters Python's str.strip() removes, U+00A0 included. */
    private const BLANKS = " \t\n\r\0\x0B\u{00A0}";

    /** What a `<br>` renders as: two spaces then a newline. */
    private const BREAK = "  \n";

    /** Tags whose own markup is dropped but whose children are kept. */
    private const TRANSPARENT = ['div', 'span', 'u', 'body', 'html', 'font', 'small', 'sub', 'sup'];

    /** Tags that start a new block. */
    private const BLOCKS = [
        'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote',
        'hr', 'pre', 'table', 'div',
    ];

    public static function fromHtml(?string $html): ?string
    {
        if ($html === null || trim($html) === '') {
            return null;
        }
        if (!str_contains($html, '<')) {
            return trim($html) ?: null;
        }

        // `<...>` and friends appear in shop copy as literal text. libxml
        // reads them as tags and drops them; html.parser (what markdownify
        // uses) leaves them alone. Escape any `<` that cannot start a tag so
        // the text survives.
        $html = preg_replace('/<(?![a-zA-Z\/!?])/', '&lt;', $html) ?? $html;

        $document = new DOMDocument();
        // Suppress the warnings malformed shop markup produces; the parser
        // recovers, and a warning per description would drown the log.
        $previous = libxml_use_internal_errors(true);
        $document->loadHTML(
            '<?xml encoding="UTF-8"?><div id="__root">' . $html . '</div>',
            LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD
        );
        libxml_clear_errors();
        libxml_use_internal_errors($previous);

        $root = $document->getElementById('__root');
        if ($root === null) {
            return trim(strip_tags($html)) ?: null;
        }

        $markdown = self::normaliseBlankLines(self::pyTrim(self::children($root)));

        return $markdown === '' ? null : $markdown;
    }

    /** Concatenate a node's children, inserting blank lines between blocks. */
    private static function children(DOMNode $node): string
    {
        $out = '';
        foreach ($node->childNodes as $child) {
            // Whitespace between block elements is layout, not content.
            // Keeping it leaves a stray " " paragraph between every two
            // blocks, which is what markdownify drops.
            if ($child instanceof DOMText && self::isBlank((string) $child->nodeValue)) {
                continue;
            }
            $rendered = self::render($child);
            if ($rendered === '') {
                continue;
            }
            if ($out !== '' && (self::isBlock($child) || self::endsBlock($out))) {
                $out = rtrim($out, "\n") . "\n\n";
            }
            $out .= $rendered;
        }

        return $out;
    }

    private static function isBlock(DOMNode $node): bool
    {
        return $node instanceof DOMElement
            && in_array(strtolower($node->nodeName), self::BLOCKS, true);
    }

    /** True when what we have already written was a block. */
    private static function endsBlock(string $text): bool
    {
        return str_ends_with($text, "\n\n");
    }

    private static function render(DOMNode $node): string
    {
        if ($node instanceof DOMText) {
            return self::text($node->nodeValue ?? '');
        }
        if (!$node instanceof DOMElement) {
            return '';
        }

        $tag = strtolower($node->nodeName);

        return match (true) {
            $tag === 'br' => self::BREAK,
            $tag === 'hr' => "---\n\n",
            $tag === 'p' => self::block(self::children($node)),
            in_array($tag, ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], true)
                => self::heading((int) substr($tag, 1), self::children($node)),
            $tag === 'b' || $tag === 'strong' => self::wrap(self::children($node), '**'),
            $tag === 'i' || $tag === 'em' => self::wrap(self::children($node), '*'),
            $tag === 'a' => self::link($node),
            $tag === 'img' => self::image($node),
            $tag === 'ul' || $tag === 'ol' => self::list($node, $tag === 'ol'),
            $tag === 'li' => self::children($node),
            $tag === 'blockquote' => self::blockquote(self::children($node)),
            $tag === 'pre' => self::pre($node),
            $tag === 'table' => self::table($node),
            $tag === 'script' || $tag === 'style' => '',
            in_array($tag, self::TRANSPARENT, true) => self::children($node),
            default => self::children($node),
        };
    }

    /**
     * A text run.
     *
     * Runs of ASCII whitespace collapse to one space; U+00A0 does not, because
     * markdownify leaves it alone and shop copy uses it deliberately (a
     * non-breaking space before a name reads as a double space if collapsed).
     * `*` and `_` are escaped so prose cannot turn into emphasis.
     */
    private static function text(string $value): string
    {
        $collapsed = preg_replace('/[ \t\r\n\f\x0B]+/u', ' ', $value) ?? $value;
        if (trim($collapsed) === '' && !str_contains($collapsed, "\u{00A0}")) {
            return $collapsed === '' ? '' : ' ';
        }

        return str_replace(['*', '_'], ['\\*', '\\_'], $collapsed);
    }

    private static function wrap(string $inner, string $marker): string
    {
        $trimmed = self::pyTrim($inner);
        if ($trimmed === '') {
            // An emphasis element holding only whitespace still contributes
            // that whitespace — dropping it joins the words either side.
            return $inner === '' ? '' : ' ';
        }
        // Leading/trailing whitespace moves outside the markers, or
        // `** bold **` stops being emphasis at all.
        $lead = ltrim($inner, self::BLANKS) !== $inner ? ' ' : '';
        $tail = rtrim($inner, self::BLANKS) !== $inner ? ' ' : '';

        return $lead . $marker . $trimmed . $marker . $tail;
    }

    /**
     * A block, closed with the blank line Markdown needs.
     *
     * The U+00A0 rule here is markdownify's, established by measurement:
     *
     *   <p>a. </p>      -> "a."      (trailing nbsp dropped)
     *   <p>a. <br></p>  -> "a. "     (kept — the <br> shields it)
     *   <p>a.<br></p>   -> "a."
     *
     * (the spaces above are U+00A0). A `<br>` at the end of a paragraph is
     * redundant markup shops emit constantly, so this is not an edge case:
     * it decides the stored text of a large share of descriptions.
     */
    private static function block(string $inner): string
    {
        $endsWithBreak = str_ends_with($inner, self::BREAK);
        $trimmed = $endsWithBreak
            ? rtrim($inner, " \t\n\r\0\x0B")
            : self::pyTrim($inner);
        $trimmed = ltrim($trimmed, self::BLANKS);

        return $trimmed === '' ? '' : $trimmed . "\n\n";
    }

    /**
     * Python's `str.strip()`, which counts U+00A0 as whitespace — PHP's
     * `trim()` does not, and that one difference accounted for every
     * remaining mismatch against markdownify: a `&nbsp;` before a closing tag
     * left a stray space at the end of a block, and one inside `<strong>`
     * moved the emphasis markers to the wrong side of it.
     *
     * Only for trimming. Collapsing still leaves U+00A0 alone mid-sentence,
     * because that is deliberate typography in shop copy.
     */
    private static function pyTrim(string $text): string
    {
        return trim($text, self::BLANKS);
    }

    /**
     * Blank for layout purposes, U+00A0 included.
     *
     * A `<p>&nbsp;</p>` spacer is not content — markdownify drops it — but a
     * U+00A0 *inside* a sentence is, so this is only used to decide whether a
     * whole node is empty, never to rewrite text.
     */
    private static function isBlank(string $text): bool
    {
        return self::pyTrim($text) === '';
    }

    private static function heading(int $level, string $inner): string
    {
        $trimmed = self::pyTrim($inner);

        return $trimmed === '' ? '' : str_repeat('#', $level) . ' ' . $trimmed . "\n\n";
    }

    private static function link(DOMElement $node): string
    {
        $text = self::pyTrim(self::children($node));
        $href = $node->getAttribute('href');
        if ($href === '') {
            return $text;
        }

        return "[{$text}]({$href})";
    }

    private static function image(DOMElement $node): string
    {
        $src = $node->getAttribute('src');
        if ($src === '') {
            return '';
        }

        return '![' . $node->getAttribute('alt') . "]({$src})";
    }

    private static function list(DOMElement $node, bool $ordered): string
    {
        $lines = [];
        $index = 1;
        foreach ($node->childNodes as $child) {
            if (!$child instanceof DOMElement || strtolower($child->nodeName) !== 'li') {
                continue;
            }
            $content = self::pyTrim(self::children($child));
            if ($content === '') {
                continue;
            }
            $lines[] = ($ordered ? "{$index}. " : '* ') . $content;
            $index++;
        }

        return $lines === [] ? '' : implode("\n", $lines) . "\n\n";
    }

    private static function blockquote(string $inner): string
    {
        $trimmed = self::pyTrim($inner);
        if ($trimmed === '') {
            return '';
        }
        $quoted = array_map(
            static fn (string $line): string => $line === '' ? '>' : "> {$line}",
            explode("\n", $trimmed)
        );

        return implode("\n", $quoted) . "\n\n";
    }

    private static function pre(DOMElement $node): string
    {
        // Code is verbatim: no whitespace collapsing, no escaping.
        $text = rtrim($node->textContent, "\n");

        return "```\n{$text}\n```\n\n";
    }

    private static function table(DOMElement $node): string
    {
        $rows = [];
        foreach ($node->getElementsByTagName('tr') as $tr) {
            $cells = [];
            foreach ($tr->childNodes as $cell) {
                if ($cell instanceof DOMElement
                    && in_array(strtolower($cell->nodeName), ['th', 'td'], true)) {
                    $cells[] = self::pyTrim(self::children($cell));
                }
            }
            if ($cells !== []) {
                $rows[] = $cells;
            }
        }
        if ($rows === []) {
            return '';
        }

        $lines = ['| ' . implode(' | ', $rows[0]) . ' |'];
        $lines[] = '| ' . implode(' | ', array_fill(0, count($rows[0]), '---')) . ' |';
        foreach (array_slice($rows, 1) as $row) {
            $lines[] = '| ' . implode(' | ', $row) . ' |';
        }

        return implode("\n", $lines) . "\n\n";
    }

    /** Collapse three-or-more newlines to the blank line Markdown needs. */
    private static function normaliseBlankLines(string $text): string
    {
        return preg_replace("/\n{3,}/", "\n\n", $text) ?? $text;
    }
}
