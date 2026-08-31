<?php

declare(strict_types=1);

namespace App\Support;

use DOMDocument;
use DOMElement;
use DOMNode;
use DOMText;

final class Markdown
{
    private const BLANKS = " \t\n\r\0\x0B\u{00A0}";

    private const BREAK = "  \n";

    private const TRANSPARENT = ['div', 'span', 'u', 'body', 'html', 'font', 'small', 'sub', 'sup'];

    private const BLOCKS = [
        'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote',
        'hr', 'pre', 'table', 'div',
    ];

    public static function fromHtml(?string $html): ?string
    {
        if ($html === null || trim($html) === '') {
            return null;
        }
        if (! str_contains($html, '<')) {
            $trimmed = trim($html);

            return $trimmed !== '' ? $trimmed : null;
        }

        $html = preg_replace('/<(?![a-zA-Z\/!?])/', '&lt;', $html) ?? $html;

        $document = new DOMDocument;

        $previous = libxml_use_internal_errors(true);
        $document->loadHTML(
            '<?xml encoding="UTF-8"?><div id="__root">'.$html.'</div>',
            LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD
        );
        libxml_clear_errors();
        libxml_use_internal_errors($previous);

        $root = $document->getElementById('__root');
        if ($root === null) {
            $trimmed = trim(strip_tags($html));

            return $trimmed !== '' ? $trimmed : null;
        }

        $markdown = self::normaliseBlankLines(self::pyTrim(self::children($root)));

        return $markdown === '' ? null : $markdown;
    }

    private static function children(DOMNode $node): string
    {
        $out = '';
        foreach ($node->childNodes as $child) {

            if ($child instanceof DOMText && self::isBlank((string) $child->nodeValue)) {
                continue;
            }
            $rendered = self::render($child);
            if ($rendered === '') {
                continue;
            }
            if ($out !== '' && (self::isBlock($child) || self::endsBlock($out))) {
                $out = rtrim($out, "\n")."\n\n";
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

    private static function endsBlock(string $text): bool
    {
        return str_ends_with($text, "\n\n");
    }

    private static function render(DOMNode $node): string
    {
        if ($node instanceof DOMText) {
            return self::text($node->nodeValue ?? '');
        }
        if (! $node instanceof DOMElement) {
            return '';
        }

        $tag = strtolower($node->nodeName);

        return match (true) {
            $tag === 'br' => self::BREAK,
            $tag === 'hr' => "---\n\n",
            $tag === 'p' => self::block(self::children($node)),
            in_array($tag, ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], true) => self::heading((int) substr($tag, 1), self::children($node)),
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

    private static function text(string $value): string
    {
        $collapsed = preg_replace('/[ \t\r\n\f\x0B]+/u', ' ', $value) ?? $value;
        if (trim($collapsed) === '' && ! str_contains($collapsed, "\u{00A0}")) {
            return $collapsed === '' ? '' : ' ';
        }

        return str_replace(['*', '_'], ['\\*', '\\_'], $collapsed);
    }

    private static function wrap(string $inner, string $marker): string
    {
        $trimmed = self::pyTrim($inner);
        if ($trimmed === '') {

            return $inner === '' ? '' : ' ';
        }

        $lead = ltrim($inner, self::BLANKS) !== $inner ? ' ' : '';
        $tail = rtrim($inner, self::BLANKS) !== $inner ? ' ' : '';

        return $lead.$marker.$trimmed.$marker.$tail;
    }

    private static function block(string $inner): string
    {
        $endsWithBreak = str_ends_with($inner, self::BREAK);
        $trimmed = $endsWithBreak
            ? rtrim($inner, " \t\n\r\0\x0B")
            : self::pyTrim($inner);
        $trimmed = ltrim($trimmed, self::BLANKS);

        return $trimmed === '' ? '' : $trimmed."\n\n";
    }

    private static function pyTrim(string $text): string
    {
        return trim($text, self::BLANKS);
    }

    private static function isBlank(string $text): bool
    {
        return self::pyTrim($text) === '';
    }

    private static function heading(int $level, string $inner): string
    {
        $trimmed = self::pyTrim($inner);

        return $trimmed === '' ? '' : str_repeat('#', $level).' '.$trimmed."\n\n";
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

        return '!['.$node->getAttribute('alt')."]({$src})";
    }

    private static function list(DOMElement $node, bool $ordered): string
    {
        $lines = [];
        $index = 1;
        foreach ($node->childNodes as $child) {
            if (! $child instanceof DOMElement || strtolower($child->nodeName) !== 'li') {
                continue;
            }
            $content = self::pyTrim(self::children($child));
            if ($content === '') {
                continue;
            }
            $lines[] = ($ordered ? "{$index}. " : '* ').$content;
            $index++;
        }

        return $lines === [] ? '' : implode("\n", $lines)."\n\n";
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

        return implode("\n", $quoted)."\n\n";
    }

    private static function pre(DOMElement $node): string
    {

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

        $lines = ['| '.implode(' | ', $rows[0]).' |'];
        $lines[] = '| '.implode(' | ', array_fill(0, count($rows[0]), '---')).' |';
        foreach (array_slice($rows, 1) as $row) {
            $lines[] = '| '.implode(' | ', $row).' |';
        }

        return implode("\n", $lines)."\n\n";
    }

    private static function normaliseBlankLines(string $text): string
    {
        return preg_replace("/\n{3,}/", "\n\n", $text) ?? $text;
    }
}
