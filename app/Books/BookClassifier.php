<?php

declare(strict_types=1);

namespace App\Books;

use App\Support\Isbn;

final class BookClassifier
{
    private const array BOOK_CATEGORY_LABELS = [
        'negrožinė literatūra',
        'grožinė literatūra',
        'knygos vaikams ir jaunimui',
        'knygos anglų kalba',
        'audioknygos',
    ];

    private const array NON_BOOK_CATEGORY_KEYWORDS = ['žaisl', 'album'];

    private const array AUDIO_FORMATS = ['audiobook', 'audio', 'audiobookas'];

    private const array EBOOK_FORMATS = ['ebook', 'e-book', 'eknyga', 'e-knyga', 'elektroninė knyga'];

    private const array BOOK_FORMATS = ['book', 'hardcover', 'paperback'];

    private const array GAME_OR_TOY_PATTERNS = [
        '/^\s*stalo\s+žaidim/u',
        '/^\s*kort[ųu]\s+žaidim/u',
        '/^\s*edukacinis\s+žaidim/u',
        '/^\s*dėlion/u',
        '/\bpuzzle\b/u',
        '/\blego\b/u',
        '/^\s*žaislas\b/u',
    ];

    /**
     * @param  array<string, mixed>  $data
     * @return array{score: int, is_book_product: bool, reasons: list<array{key: string, points: int}>, has_primary_book_signal: bool}
     */
    public static function classify(array $data): array
    {
        $title = $data['title'] ?? null;
        if (! is_string($title) || trim($title) === '') {
            return [
                'score' => 0,
                'is_book_product' => false,
                'reasons' => [['key' => 'no_title', 'points' => 0]],
                'has_primary_book_signal' => false,
            ];
        }

        $categories = $data['categories'] ?? null;
        $hasBookCategory = self::categoriesContainLabels($categories, self::BOOK_CATEGORY_LABELS);
        $hasNonBookCategory = self::categoriesContainKeywords(
            $categories,
            self::NON_BOOK_CATEGORY_KEYWORDS,
        );
        $isbn = $data['isbn'] ?? null;
        $validIsbn = Isbn::isValid(is_string($isbn) ? $isbn : null);
        $author = $data['author'] ?? null;
        $hasAuthor = is_string($author) && trim($author) !== '';

        $hasBookMetadata = false;
        foreach (['pages', 'cover_type', 'year', 'translator', 'narrator', 'duration', 'format'] as $field) {
            $value = $data[$field] ?? null;
            if ($value !== null && $value !== '') {
                $hasBookMetadata = true;
                break;
            }
        }

        $titleIsNonBook = self::titleLooksLikeGameOrToy($title);
        $signals = [
            ['book_categories', $hasBookCategory, 3],
            ['valid_isbn', $validIsbn, 3],
            ['author_present', $hasAuthor, 2],
            ['book_metadata', $hasBookMetadata, 2],
            ['game_toy_title', $titleIsNonBook, -3],
            ['non_book_categories', $hasNonBookCategory, -4],
        ];

        $score = 0;
        $reasons = [];
        foreach ($signals as [$key, $fired, $points]) {
            $awarded = $fired ? $points : 0;
            $score += $awarded;
            $reasons[] = ['key' => $key, 'points' => $awarded];
        }

        if ($hasNonBookCategory && ! ($hasBookCategory || $validIsbn || $hasAuthor)) {
            $reasons[] = ['key' => 'blocked_non_book_category', 'points' => 0];

            return [
                'score' => $score,
                'is_book_product' => false,
                'reasons' => $reasons,
                'has_primary_book_signal' => false,
            ];
        }
        if ($titleIsNonBook && ! ($hasBookCategory || $validIsbn || $hasBookMetadata)) {
            $reasons[] = ['key' => 'blocked_game_toy_title', 'points' => 0];

            return [
                'score' => $score,
                'is_book_product' => false,
                'reasons' => $reasons,
                'has_primary_book_signal' => false,
            ];
        }

        $hasPrimary = $hasBookCategory || $validIsbn || ($hasAuthor && $hasBookMetadata);

        return [
            'score' => $score,
            'is_book_product' => $score >= 3 && $hasPrimary,
            'reasons' => $reasons,
            'has_primary_book_signal' => $hasPrimary,
        ];
    }

    /** @param array<string, mixed> $data */
    public static function inferType(array $data): string
    {
        $format = $data['format'] ?? null;
        $normalized = is_string($format) ? self::normalizeText($format) : '';

        if (in_array($normalized, self::AUDIO_FORMATS, true)) {
            return 'audio';
        }
        if (in_array($normalized, self::EBOOK_FORMATS, true)) {
            return 'ebook';
        }
        if (in_array($normalized, self::BOOK_FORMATS, true)) {
            return 'book';
        }

        $categories = $data['categories'] ?? null;
        if (self::categoriesContainKeywords($categories, ['audioknyg', 'audiokny'])) {
            return 'audio';
        }
        if (self::categoriesContainKeywords($categories, ['e-knyg', 'eknyg', 'elektronin'])) {
            return 'ebook';
        }

        return self::classify($data)['is_book_product'] ? 'book' : 'non_book';
    }

    public static function titleLooksLikeGameOrToy(?string $title): bool
    {
        if ($title === null || $title === '') {
            return false;
        }
        $normalized = self::normalizeText($title);

        return array_any(self::GAME_OR_TOY_PATTERNS, fn ($pattern): bool => preg_match($pattern, $normalized) === 1);
    }

    /** @param list<string> $keywords */
    private static function categoriesContainKeywords(mixed $categories, array $keywords): bool
    {
        if (! is_array($categories)) {
            return false;
        }
        foreach ($categories as $category) {
            if (! is_string($category)) {
                continue;
            }
            $normalized = self::normalizeText($category);
            foreach ($keywords as $keyword) {
                if (str_contains($normalized, $keyword)) {
                    return true;
                }
            }
        }

        return false;
    }

    /** @param list<string> $labels */
    private static function categoriesContainLabels(mixed $categories, array $labels): bool
    {
        if (! is_array($categories)) {
            return false;
        }
        $normalized = [];
        foreach ($categories as $category) {
            if (is_string($category)) {
                $normalized[self::normalizeText($category)] = true;
            }
        }

        return array_any($labels, fn ($label): bool => isset($normalized[$label]));
    }

    private static function normalizeText(string $value): string
    {
        $unescaped = html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $lowered = mb_strtolower($unescaped, 'UTF-8');

        return trim(preg_replace('/\s+/u', ' ', $lowered) ?? $lowered);
    }
}
