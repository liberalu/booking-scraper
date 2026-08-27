<?php

declare(strict_types=1);

namespace App\Parsers\Vaga;

use App\Support\CoverType;
use App\Support\Isbn;
use Symfony\Component\DomCrawler\Crawler;

/**
 * Port of book_scraper/spiders/vaga/parsers.py.
 *
 * vaga.lt is OpenCart: product pages carry JSON-LD plus a block of
 * `propery-title`/`propery-des` span pairs (the class typo is theirs and
 * load-bearing). Regex over raw HTML is kept rather than DOM-walking so
 * this stays a line-for-line port of the Python that is already correct
 * in production; DomCrawler is used only where the Python used
 * BeautifulSoup.
 */
final class Parser
{
    /**
     * Card price. vaga varies the modifier on the class ("price special"
     * today, "price coupon" before that, sometimes none), and pinning one is
     * how the listing silently stopped yielding prices: every card parsed and
     * every price came back null. Requiring `"` or whitespace after `price`
     * keeps this off `price-old`, `price-filter` and `product-price`, which
     * sit in the same card.
     */
    private const CARD_PRICE = '/class="price(?:\s+[a-z-]+)*"[^>]*>\s*([0-9,]+)€/u';

    /**
     * The "was" price: `price-old price-in-store` today, with a "Knygyne:"
     * label before the number; `price-old strikethrough` and a bare
     * `price-old` also occur.
     */
    private const CARD_PRICE_OLD = '/class="price-old[^"]*"[^>]*>[^<]*?([0-9,]+)€/u';

    private const BOOK_CATEGORY_LABELS = [
        'negrožinė literatūra',
        'grožinė literatūra',
        'knygos vaikams ir jaunimui',
        'knygos anglų kalba',
        'audioknygos',
    ];

    /**
     * Intentionally narrow: only product types that can never be books.
     * Ambiguous placement categories ("dovanų idėjos") would falsely
     * block real books.
     */
    private const NON_BOOK_CATEGORY_KEYWORDS = ['žaisl', 'album'];

    private const AUDIO_FORMATS = ['audiobook', 'audio', 'audiobookas'];
    private const EBOOK_FORMATS = ['ebook', 'e-book', 'eknyga', 'e-knyga', 'elektroninė knyga'];
    private const BOOK_FORMATS = ['book', 'hardcover', 'paperback'];

    private const GAME_OR_TOY_PATTERNS = [
        '/^\s*stalo\s+žaidim/u',
        '/^\s*kort[ųu]\s+žaidim/u',
        '/^\s*edukacinis\s+žaidim/u',
        '/^\s*dėlion/u',
        '/\bpuzzle\b/u',
        '/\blego\b/u',
        '/^\s*žaislas\b/u',
    ];

    private const ALLOWED_DESCRIPTION_TAGS = [
        'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'ul', 'ol', 'li',
    ];

    // ---------------------------------------------------------------- sitemap

    /** @return list<string> */
    public static function parseSitemapUrls(string $xml): array
    {
        // loadXML() raises ValueError on an empty string instead of
        // returning false, so this guard has to come first.
        if (trim($xml) === '') {
            return [];
        }

        $doc = new \DOMDocument();
        // Sitemaps are machine-generated; surface real breakage, ignore
        // libxml's chatter about unknown entities.
        $prev = libxml_use_internal_errors(true);
        $ok = $doc->loadXML($xml);
        libxml_use_internal_errors($prev);
        if ($ok === false) {
            return [];
        }

        $xpath = new \DOMXPath($doc);
        $xpath->registerNamespace('s', 'http://www.sitemaps.org/schemas/sitemap/0.9');
        $urls = [];
        foreach ($xpath->query('//s:loc') ?: [] as $node) {
            if ($node->textContent !== '') {
                $urls[] = $node->textContent;
            }
        }

        return $urls;
    }

    // --------------------------------------------------------------- category

    /**
     * OpenCart prints "Rodoma nuo 1 iki 100 iš 9910" on every listing
     * page; returning that total lets the spider enqueue all pages
     * upfront so concurrency actually engages instead of chaining page
     * by page.
     *
     * @return array{products: list<array<string, string|null>>, total: int|null}
     */
    public static function parseCategoryPage(string $html): array
    {
        $products = [];
        $segments = preg_split('/class="product-item-container product-\d+"/u', $html) ?: [];
        foreach (array_slice($segments, 1) as $seg) {
            if (preg_match('/<p class="name"><a href="([^"]+)">([^<]+)/u', $seg, $name) !== 1) {
                continue;
            }

            $products[] = [
                'url' => trim(explode('?', $name[1])[0]),
                'title' => self::unescape(trim($name[2])),
                'author' => self::firstGroup('/<p class="Autorius">\s*([^<]+?)\s*<\/p>/u', $seg),
                // Lithuanian decimal comma: '16,32€' -> '16.32'
                'price' => self::firstPrice(self::CARD_PRICE, $seg),
                'price_original' => self::firstPrice(self::CARD_PRICE_OLD, $seg),
                'image_url' => self::firstGroup('/data-src="([^"]+)"/u', $seg, unescape: false),
            ];
        }

        $total = null;
        if (preg_match('/Rodoma nuo \d+ iki \d+ iš (\d+)/u', $html, $m) === 1) {
            $total = (int) $m[1];
        }

        return ['products' => $products, 'total' => $total];
    }

    // ---------------------------------------------------------------- product

    /** @return array<string, mixed> */
    public static function parseProductPage(string $html): array
    {
        $data = [
            'title' => null, 'description' => null, 'price' => null,
            'price_original' => null, 'in_stock' => null, 'isbn' => null,
            'sku' => null, 'publisher' => null, 'image_url' => null,
            'categories' => [], 'year' => null, 'pages' => null,
            'author' => null, 'cover_type' => null, 'format' => null,
            'duration' => null, 'narrator' => null, 'translator' => null,
            'schema_types' => [], 'is_book_product' => false, 'book_score' => 0,
            'book_score_reasons' => [], 'type' => 'book',
            'planned_availability_date' => null, 'rating' => null,
            'review_count' => null,
        ];

        // <div class="brand"><span>Autorius </span><a>Name</a></div>
        $data['author'] = self::firstGroup(
            '/class="brand">\s*<span>Autorius\s*<\/span>\s*<a[^>]*>([^<]+)<\/a>/u',
            $html
        );

        $schemaTypes = [];
        preg_match_all(
            '/<script type="application\/ld\+json">\s*(.*?)\s*<\/script>/us',
            $html,
            $blocks
        );
        foreach ($blocks[1] as $block) {
            $cleaned = preg_replace('/[\x00-\x1f]+/', ' ', trim($block)) ?? '';
            $ld = json_decode($cleaned, true);
            if (!is_array($ld)) {
                continue;
            }

            $ldTypes = array_map('strval', (array) ($ld['@type'] ?? []));
            $schemaTypes = [...$schemaTypes, ...$ldTypes];

            if (in_array('Product', $ldTypes, true) || in_array('Book', $ldTypes, true)) {
                $offers = (array) ($ld['offers'] ?? []);
                $data['title'] = self::unescapeMixed($ld['name'] ?? null);
                $data['description'] = self::unescapeMixed($ld['description'] ?? null);
                $data['sku'] = $ld['sku'] ?? null;
                $data['price'] = $offers['price'] ?? null;
                $data['in_stock'] = str_contains((string) ($offers['availability'] ?? ''), 'InStock');
                $data['isbn'] = ((array) ($ld['isRelatedTo'] ?? []))['isbn'] ?? null;
                $data['publisher'] = self::unescapeMixed(((array) ($ld['brand'] ?? []))['name'] ?? null);
                $images = $ld['image'] ?? [];
                if ($images !== [] && $images !== null) {
                    $data['image_url'] = is_array($images) ? ($images[0] ?? null) : $images;
                }
            }

            if (($ld['@type'] ?? null) === 'BreadcrumbList') {
                $data['categories'] = array_values(array_map(
                    static fn (array $item): string => self::unescape((string) $item['name']),
                    array_filter(
                        (array) ($ld['itemListElement'] ?? []),
                        static fn (mixed $item): bool => is_array($item) && ($item['name'] ?? '') !== ''
                    )
                ));
            }
        }

        // A "price-new special"/"price-new coupon" layout shows a price that
        // DIFFERS from JSON-LD offers.price. The page shows this value and no
        // strikethrough original, so it is authoritative — and the JSON-LD
        // value on those layouts is a non-public wholesale/club price that
        // would mislead users as a "was" price. Drop it, don't promote it.
        $special = self::firstPrice('/class="price-new (?:special|coupon)"[^>]*>\s*([\d,]+)€/u', $html);
        if ($special !== null) {
            $data['price'] = $special;
        }

        // Original bookstore price lives only in HTML, not JSON-LD.
        $data['price_original'] = self::firstPrice('/class="price-knygyne">([0-9,]+)€/u', $html)
            ?? $data['price_original'];

        // Prefer the rich-text description block over the flat JSON-LD value.
        if (preg_match('/<div[^>]*id=["\']collapse-description["\'][^>]*>(.*?)<\/div>/uis', $html, $desc) === 1) {
            $rich = self::sanitizeDescriptionHtml($desc[1]);
            if ($rich !== '') {
                $data['description'] = self::unescape($rich);
            }
        }

        // Property spans (note the shop's own "propery" typo).
        preg_match_all(
            '/<span class="propery-title">(.*?)<\/span>\s*<span class="propery-des">(.*?)<\/span>/u',
            $html,
            $props,
            PREG_SET_ORDER
        );
        $propMap = [];
        foreach ($props as $pair) {
            $propMap[trim($pair[1])] = self::unescape(trim($pair[2]));
        }

        $data['isbn'] = $data['isbn'] ?? ($propMap['ISBN'] ?? null);
        $data['year'] = self::toIntOrNull($propMap['Metai'] ?? null);
        $data['pages'] = self::toIntOrNull($propMap['Puslapiai'] ?? null);
        $data['cover_type'] = $propMap['Viršelis'] ?? null;
        $data['publisher'] = $data['publisher'] ?? ($propMap['Leidykla'] ?? null);
        $data['duration'] = $propMap['Trukmė'] ?? null;
        $data['narrator'] = $propMap['Įgarsino'] ?? null;
        $data['translator'] = $propMap['Vertėjas'] ?? null;

        // Only trust Trukmė when non-zero: vaga leaves "0 val. 00 min." on
        // regular books, which would misclassify textbooks as audiobooks.
        $trukme = trim($propMap['Trukmė'] ?? '');
        if ($trukme !== '' && preg_match('/[1-9]/', $trukme) === 1) {
            $data['format'] = 'audiobook';
        } elseif (isset($propMap['Viršelis'])) {
            $data['format'] = CoverType::toFormat($propMap['Viršelis']);
        } elseif (isset($propMap['Puslapiai'])) {
            $data['format'] = 'book';
        }

        $crawler = new Crawler($html);
        $data['planned_availability_date'] = self::plannedAvailabilityDate($crawler);
        $data['rating'] = self::rating($crawler);
        $data['review_count'] = self::reviewCount($crawler);

        $schemaTypes = array_values(array_unique($schemaTypes));
        sort($schemaTypes);
        $data['schema_types'] = $schemaTypes;

        $classification = self::classifyBookProduct($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = self::inferShopBookType($data);

        return $data;
    }

    // --------------------------------------------------------- classification

    /**
     * @param  array<string, mixed>  $data
     * @return array{score: int, is_book_product: bool, reasons: list<array{key: string, points: int}>, has_primary_book_signal: bool}
     */
    public static function classifyBookProduct(array $data): array
    {
        $title = $data['title'] ?? null;
        if (!is_string($title) || trim($title) === '') {
            return [
                'score' => 0,
                'is_book_product' => false,
                'reasons' => [['key' => 'no_title', 'points' => 0]],
                'has_primary_book_signal' => false,
            ];
        }

        $categories = $data['categories'] ?? null;
        $hasBookCategory = self::categoriesContainLabels($categories, self::BOOK_CATEGORY_LABELS);
        $hasNonBookCategory = self::categoriesContainKeywords($categories, self::NON_BOOK_CATEGORY_KEYWORDS);
        $validIsbn = Isbn::isValid(is_string($data['isbn'] ?? null) ? $data['isbn'] : null);
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

        if ($hasNonBookCategory && !($hasBookCategory || $validIsbn || $hasAuthor)) {
            $reasons[] = ['key' => 'blocked_non_book_category', 'points' => 0];

            return ['score' => $score, 'is_book_product' => false, 'reasons' => $reasons, 'has_primary_book_signal' => false];
        }
        if ($titleIsNonBook && !($hasBookCategory || $validIsbn || $hasBookMetadata)) {
            $reasons[] = ['key' => 'blocked_game_toy_title', 'points' => 0];

            return ['score' => $score, 'is_book_product' => false, 'reasons' => $reasons, 'has_primary_book_signal' => false];
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
    public static function isBookProductPage(array $data): bool
    {
        return self::classifyBookProduct($data)['is_book_product'];
    }

    /**
     * @param  array<string, mixed>  $data
     * @return 'book'|'audio'|'ebook'|'non_book'
     */
    public static function inferShopBookType(array $data): string
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

        return self::classifyBookProduct($data)['is_book_product'] ? 'book' : 'non_book';
    }

    public static function titleLooksLikeGameOrToy(?string $title): bool
    {
        if ($title === null || $title === '') {
            return false;
        }
        $normalized = self::normalizeText($title);
        foreach (self::GAME_OR_TOY_PATTERNS as $pattern) {
            if (preg_match($pattern, $normalized) === 1) {
                return true;
            }
        }

        return false;
    }

    // ------------------------------------------------------------- description

    /**
     * Strip everything outside a small tag allowlist. Attributes are
     * dropped; script/style blocks go with their contents. Output is safe
     * to render unescaped in a template.
     */
    public static function sanitizeDescriptionHtml(string $markup): string
    {
        $markup = preg_replace('/<(script|style)\b[^>]*>.*?<\/\1>/uis', '', $markup) ?? $markup;
        $markup = preg_replace('/<!--.*?-->/us', '', $markup) ?? $markup;
        $markup = preg_replace_callback(
            '/<(\/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>/u',
            static function (array $m): string {
                $tag = strtolower($m[2]);

                return in_array($tag, self::ALLOWED_DESCRIPTION_TAGS, true) ? "<{$m[1]}{$tag}>" : '';
            },
            $markup
        ) ?? $markup;

        return trim($markup);
    }

    // ---------------------------------------------------------- DOM extraction

    private static function plannedAvailabilityDate(Crawler $crawler): ?string
    {
        $text = self::firstNodeText($crawler, '.form-group.isankstine .information-content span');
        if ($text === null) {
            // Fallback: any span carrying the Lithuanian phrase.
            foreach ($crawler->filter('span') as $span) {
                if (str_contains($span->textContent, 'Planuojame turėti')) {
                    $text = trim($span->textContent);
                    break;
                }
            }
        }
        if ($text === null) {
            return null;
        }

        return preg_match('/(\d{4}-\d{2}-\d{2})/', $text, $m) === 1 ? $m[1] : null;
    }

    /** Count filled stars; null when nothing is rated. */
    private static function rating(Crawler $crawler): ?float
    {
        // first() is load-bearing: a product page carries ~25 .rating-box
        // elements (the related-products carousel), and a rated neighbour
        // would otherwise donate its stars to this book.
        $box = $crawler->filter('.rating-box')->first();
        if ($box->count() === 0) {
            return null;
        }
        $stacks = $box->filter('.fa.fa-stack');
        if ($stacks->count() === 0) {
            return null;
        }
        $filled = $stacks->reduce(
            static fn (Crawler $s): bool => $s->filter('i.fa-star:not(.fa-star-o)')->count() > 0
        )->count();

        return $filled > 0 ? (float) $filled : null;
    }

    private static function reviewCount(Crawler $crawler): ?int
    {
        $text = self::firstNodeText($crawler, 'a.reviews_button');
        if ($text === null) {
            return null;
        }

        return preg_match('/^(\d+)/', $text, $m) === 1 ? (int) $m[1] : null;
    }

    private static function firstNodeText(Crawler $crawler, string $selector): ?string
    {
        $node = $crawler->filter($selector);

        return $node->count() > 0 ? trim($node->first()->text()) : null;
    }

    // ----------------------------------------------------------------- helpers

    /** @param mixed $categories */
    private static function categoriesContainKeywords(mixed $categories, array $keywords): bool
    {
        if (!is_array($categories)) {
            return false;
        }
        foreach ($categories as $category) {
            if (!is_string($category)) {
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

    /** @param mixed $categories */
    private static function categoriesContainLabels(mixed $categories, array $labels): bool
    {
        if (!is_array($categories)) {
            return false;
        }
        $normalized = [];
        foreach ($categories as $category) {
            if (is_string($category)) {
                $normalized[self::normalizeText($category)] = true;
            }
        }
        foreach ($labels as $label) {
            if (isset($normalized[$label])) {
                return true;
            }
        }

        return false;
    }

    /** Mirrors Python's `re.sub(r"\s+", " ", unescape(v).casefold()).strip()`. */
    private static function normalizeText(string $value): string
    {
        $lowered = mb_strtolower(self::unescape($value), 'UTF-8');

        return trim(preg_replace('/\s+/u', ' ', $lowered) ?? $lowered);
    }

    private static function unescape(string $value): string
    {
        return html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    private static function unescapeMixed(mixed $value): mixed
    {
        return is_string($value) ? self::unescape($value) : $value;
    }

    private static function firstGroup(string $pattern, string $subject, bool $unescape = true): ?string
    {
        if (preg_match($pattern, $subject, $m) !== 1) {
            return null;
        }
        $value = trim($m[1]);

        return $unescape ? self::unescape($value) : $value;
    }

    /** Lithuanian decimal comma to dot; null when the pattern misses. */
    private static function firstPrice(string $pattern, string $subject): ?string
    {
        return preg_match($pattern, $subject, $m) === 1 ? str_replace(',', '.', $m[1]) : null;
    }

    private static function toIntOrNull(?string $value): ?int
    {
        if ($value === null || preg_match('/^-?\d+$/', trim($value)) !== 1) {
            return null;
        }

        return (int) trim($value);
    }
}
