<?php

declare(strict_types=1);

namespace App\Parsers\Humanitas;

use App\Support\CoverType;
use App\Support\Isbn;
use App\Parsers\Vaga\Parser as BookClassifier;

/**
 * Port of book_scraper/spiders/humanitas/parsers.py.
 *
 * WordPress/CMSMS behind a Cloudflare Managed Challenge, so every fetch
 * goes through FlareSolverr. Listing pages render `<a class="book-item">`
 * cards; product pages carry a `<div class="book-info">` block of
 * `<b>Label:</b> Value <br>` rows.
 */
final class Parser
{
    private const BASE_URL = 'https://www.humanitas.lt';

    /** `<a>` carrying class="…book-item…" and href, attributes in any order. */
    private const PRODUCT_ANCHOR = '/<a\b(?=[^>]*\bclass="[^"]*\bbook-item\b[^"]*")[^>]*\bhref="([^"]+)"/i';

    private const CARD_OPENING = '/<a\b(?=[^>]*\bclass="[^"]*\bbook-item\b[^"]*")[^>]*\bhref="([^"]+)"[^>]*>/si';

    /**
     * Language gate, same rationale as pegasas: humanitas mixes LT and EN
     * titles under LT-named category branches, so `Leidinio kalba` is the
     * only reliable signal. Rows without the field fall through — losing
     * legacy imports would cost real LT books.
     */
    private const LANG_LITHUANIAN = 'Lietuvių';

    /** Yoast/CMSMS appends this to every <title>. */
    private const TITLE_SUFFIX = '/\s*-\s*Humanitas\s*$/i';

    private const BOOK_INFO_BLOCK = '/<div\s+class="book-info">(.*?)<\/div>/si';

    /**
     * `<b>Label:?</b> Value <br>`. The colon is optional and may fall
     * outside the `<b>` when the rendered HTML wraps a long label.
     */
    private const BOOK_INFO_ROW = '/<b>\s*([^<]+?)\s*:?\s*<\/b>\s*([^<]+?)\s*(?:<br|<b>|<\/div>)/si';

    private const PRICE = '/([\d ]+[.,]\d+)\s*€/u';

    /**
     * Script blocks are stripped before any rendered-HTML sniff: the
     * template inlines `var out_of_stock = 'Likutis nepakankamas';` on every
     * product, which would otherwise mark all of them out of stock.
     */
    private const SCRIPT_BLOCK = '/<script\b.*?<\/script>/si';

    /** Unbuyable signal 1: the price block gains a `price-hidden` class. */
    private const OOS_PRICE_HIDDEN = '/<div\s+class="cart-price\s+price-hidden\b/i';

    /** Unbuyable signal 2: the add-to-cart anchor is `disabled`. */
    private const OOS_CART_DISABLED = '/<a\b[^>]*\bclass="[^"]*\bext_button\b[^"]*\bdisabled\b/i';

    private const CART_PRICE_BLOCK_OPEN = '/<div\s+class="cart-price[^"]*"[^>]*>/i';
    private const PRICE_CONTAINER = '/<div\s+class="price-container"/i';

    private const CARD_TITLE = '/<div\s+class="title"[^>]*>\s*([^<]+?)\s*<\/div>/i';
    private const CARD_AUTHOR = '/<div\s+class="author"[^>]*>\s*([^<]+?)\s*<\/div>/i';
    private const CARD_PRICE_PAIR = '/<div\s+class="price-container"[^>]*>\s*'
        . '<div\s+class="discount"[^>]*>\s*([^<]+?)\s*<\/div>\s*'
        . '<div\s+class="price"[^>]*>\s*([^<]+?)\s*<\/div>/si';
    private const CARD_SINGLE_PRICE = '/<div\s+class="price"[^>]*>\s*([\d ]+[.,]\d+\s*€)\s*<\/div>/i';
    private const CARD_IMG = '/<img\s[^>]*\bsrc="([^"]+)"/i';

    /**
     * How far past the cart-price open tag to look for a price. Real blocks
     * are 80–200 chars in both the priced and empty state, so 600 covers any
     * priced layout without spilling into sibling blocks.
     */
    private const CART_PRICE_WINDOW = 600;

    // --------------------------------------------------------------- sitemap

    /**
     * Product URLs from a catalogue index page.
     *
     * humanitas has no XML sitemap: the "sitemap" slot is the paginated
     * catalogue root, which renders `<a class="book-item">` cards. The name
     * reflects the strategy slot, not the format.
     *
     * @return list<string>
     */
    public static function parseSitemapUrls(string $html): array
    {
        preg_match_all(self::PRODUCT_ANCHOR, $html, $matches);

        $out = [];
        foreach ($matches[1] as $raw) {
            $url = self::canonicalProductUrl($raw);
            if ($url !== null) {
                $out[] = $url;
            }
        }

        return $out;
    }

    // -------------------------------------------------------- category page

    /**
     * Products from a catalogue listing page.
     *
     * Card bodies are sliced between consecutive opening tags rather than
     * matched with a non-greedy `.*?</a>`: cards contain inner anchors
     * (wishlist, add-to-cart), and the non-greedy form terminates at the
     * first `</a>` — silently dropping title, author and price.
     *
     * `total` is null. Pagination is unreliable under the language filter:
     * pages 1 and 2 overlap ~99% at any limit (a CMSMS quirk), so the spider
     * relies on stop-when-empty plus a low max_pages cap.
     *
     * @return array{products: list<array<string, mixed>>, total: null}
     */
    public static function parseCategoryPage(string $html): array
    {
        preg_match_all(self::CARD_OPENING, $html, $openings, PREG_OFFSET_CAPTURE | PREG_SET_ORDER);

        $products = [];
        $seen = [];
        $count = count($openings);

        for ($i = 0; $i < $count; $i++) {
            $opening = $openings[$i];
            $bodyStart = $opening[0][1] + strlen($opening[0][0]);
            $bodyEnd = $i + 1 < $count ? $openings[$i + 1][0][1] : strlen($html);

            $product = self::parseCard(
                $opening[1][0],
                substr($html, $bodyStart, $bodyEnd - $bodyStart)
            );
            if ($product === null || isset($seen[$product['url']])) {
                continue;
            }
            $seen[$product['url']] = true;
            $products[] = $product;
        }

        return ['products' => $products, 'total' => null];
    }

    /**
     * @return array<string, mixed>|null  null when the anchor isn't a product
     */
    private static function parseCard(string $href, string $body): ?array
    {
        $url = self::canonicalProductUrl($href);
        if ($url === null) {
            return null;
        }

        $title = preg_match(self::CARD_TITLE, $body, $m) === 1 ? self::unescape($m[1]) : null;
        if ($title === null) {
            // Styled as a book-item but carries no title — a navigation tile.
            return ['url' => $url];
        }

        $price = null;
        $priceOriginal = null;
        if (preg_match(self::CARD_PRICE_PAIR, $body, $pair) === 1) {
            $price = self::parsePrice($pair[1]);
            $priceOriginal = self::parsePrice($pair[2]);
        } elseif (preg_match(self::CARD_SINGLE_PRICE, $body, $single) === 1) {
            // No online discount: one price, no price-container wrapper.
            $price = self::parsePrice($single[1]);
        }

        return [
            'url' => $url,
            'title' => $title,
            'author' => preg_match(self::CARD_AUTHOR, $body, $a) === 1 ? self::unescape($a[1]) : null,
            'price' => $price,
            'price_original' => $priceOriginal,
            'image_url' => preg_match(self::CARD_IMG, $body, $img) === 1 ? $img[1] : null,
            // Listing cards carry no stock signal — humanitas hides
            // out-of-stock items from listings entirely. Default true so
            // prices.in_stock (NOT NULL) gets a sane value; the scan
            // overwrites it from the detail page.
            'in_stock' => true,
        ];
    }

    // --------------------------------------------------------- product page

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

        $ogTitle = self::metaContent($html, 'og:title');
        $rawTitle = preg_match('/<title>([^<]*)<\/title>/si', $html, $t) === 1
            ? self::unescape($t[1])
            : null;
        $data['title'] = $ogTitle
            ?? ($rawTitle !== null ? preg_replace(self::TITLE_SUFFIX, '', $rawTitle) : null);

        $description = self::metaContent($html, 'og:description');
        if ($description !== null) {
            $data['description'] = $description;
        }
        $image = self::metaContent($html, 'og:image');
        if ($image !== null) {
            $data['image_url'] = $image;
        }

        // The cart container's internal product id serves as our SKU.
        if (preg_match('/data-product-id="([^"]+)"/', $html, $sku) === 1) {
            $data['sku'] = $sku[1];
        }

        [$price, $priceOriginal, $inStock] = self::extractPricePair($html);
        $data['price'] = $price;
        $data['price_original'] = $priceOriginal;
        $data['in_stock'] = $inStock;

        $properties = [];
        $info = self::extractBookInfo($html);

        if ($info !== []) {
            if (($info['ISBN'] ?? '') !== '') {
                // isValid covers ISBN-10 (older LT books with the 9986
                // prefix) and ISBN-13, with a real checksum — so non-book
                // GTINs from sticker kits and puzzles drop out here.
                $isbn = Isbn::normalize($info['ISBN']);
                if (Isbn::isValid($isbn)) {
                    $data['isbn'] = $isbn;
                }
            }
            $data['author'] = $info['Autorius'] ?? $data['author'];
            $data['publisher'] = $info['Leidėjas'] ?? $info['Leidykla'] ?? $data['publisher'];
            $data['year'] = self::intOrNull($info['Leidimo metai'] ?? null);
            $data['pages'] = self::intOrNull($info['Puslapių skaičius'] ?? null);
            $data['translator'] = $info['Vertėjas'] ?? $data['translator'];

            // `Formatas:` overloads two unrelated fields: the binding
            // ("Kieti viršeliai") and physical dimensions in many shapes
            // ("240 x 202", "9.25×7.5", "23,5x18 cm."). Dimensions must not
            // land in `format`, and "pasirinkite" is the empty selector.
            $cover = $info['Formatas'] ?? null;
            if ($cover !== null) {
                $looksLikeDimensions = preg_match('/^\s*\d+(?:[.,]\d+)?\s*[xX×]\s*\d+/u', $cover) === 1;
                $isPlaceholder = mb_strtolower(trim($cover), 'UTF-8') === 'pasirinkite';

                if (!$looksLikeDimensions && !$isPlaceholder) {
                    $data['cover_type'] = $cover;
                    $data['format'] = CoverType::toFormat($cover);
                } elseif ($looksLikeDimensions) {
                    // Kept verbatim: useful for cross-shop matching even
                    // without a first-class column.
                    $properties['dimensions'] = $cover;
                }
            }
            if (isset($info['Matmenys'])) {
                $properties['dimensions'] = $info['Matmenys'];
            }
            if (($info['Leidinio kalba'] ?? '') !== '') {
                $properties['language'] = $info['Leidinio kalba'];
            }
        }

        if ($properties !== []) {
            $data['properties'] = $properties;
        }

        $classification = BookClassifier::classifyBookProduct($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = BookClassifier::inferShopBookType($data);

        // Language gate applied AFTER classification so book_score still
        // reflects the real signal mix; only is_book_product flips, which
        // makes the scan mark the URL non_product and skip the insert. A
        // missing language attribute lets the row through, same as pegasas.
        $language = $properties['language'] ?? null;
        if (is_string($language) && trim($language) !== ''
            && trim($language) !== self::LANG_LITHUANIAN) {
            $data['is_book_product'] = false;
            $data['book_score_reasons'][] = [
                'key' => 'blocked_non_lt_language',
                'points' => 0,
                'language' => trim($language),
            ];
        }

        return $data;
    }

    /** Test convenience: the same URL set as parseSitemapUrls, richer shape. */
    public static function parseIndexPage(string $html): array
    {
        return array_map(
            static fn (string $url): array => ['url' => $url],
            self::parseSitemapUrls($html)
        );
    }

    // -------------------------------------------------------------- pricing

    /**
     * (price, price_original, in_stock) from the cart block.
     *
     * The cart container is canonical: the "Pilna kaina" banner sometimes
     * renders without the discounted cart price (out-of-stock listings,
     * pre-orders), and reading from the cart keeps the pair together.
     *
     * @return array{0: string|null, 1: string|null, 2: bool}
     */
    private static function extractPricePair(string $html): array
    {
        $section = preg_match(
            '/<div\s+class="cart-container"[^>]*>(.*?)<\/div>\s*<\/div>\s*<\/div>/si',
            $html,
            $cart
        ) === 1 ? $cart[0] : $html;

        $price = null;
        $priceOriginal = null;

        if (preg_match(
            '/<div\s+class="price-container">.*?<div\s+class="discount">'
            . '\s*([^<]+)<\/div>\s*<div\s+class="price">\s*([^<]+)<\/div>/si',
            $section,
            $final
        ) === 1) {
            $price = self::parsePrice($final[1]);
            $priceOriginal = self::parsePrice($final[2]);
        }

        if ($price === null) {
            // Some listings skip the price-container split and print one
            // price under .cart-price (items the flat 5% online discount
            // doesn't apply to).
            if (preg_match(
                '/<div\s+class="cart-price".*?(?:<div\s+class="label">[^<]*<\/div>)?'
                . '\s*([\d ]+[.,]\d+\s*€)/si',
                $section,
                $single
            ) === 1) {
                $price = self::parsePrice($single[1]);
            }
        }

        if ($priceOriginal === null) {
            if (preg_match(
                '/<div\s+class="full-price"[^>]*>.*?<div\s+class="label">[^<]*<\/div>'
                . '\s*([\d ]+[.,]\d+\s*€)/si',
                $html,
                $full
            ) === 1) {
                $priceOriginal = self::parsePrice($full[1]);
            }
        }

        $price ??= $priceOriginal;

        // in_stock is NOT NULL in the schema, so always emit a boolean.
        // Default true (most listings are in stock) and flip on any of the
        // three unbuyable signals. Scripts are stripped first so the inline
        // `out_of_stock` JS variable isn't mistaken for one.
        $visible = preg_replace(self::SCRIPT_BLOCK, '', $html) ?? $html;
        $inStock = !(
            preg_match(self::OOS_PRICE_HIDDEN, $visible) === 1
            || preg_match(self::OOS_CART_DISABLED, $visible) === 1
            || self::cartPriceBlockIsEmpty($visible)
        );

        return [$price, $priceOriginal, $inStock];
    }

    /**
     * Third unbuyable state: a cart-price block exists carrying the "Kaina:"
     * label but no price element — no price-container child and no inline
     * euro value. The cart button is NOT disabled here, so the other
     * detectors miss it. Seen in 60/60 captured bodies on 2026-05-27, ~3.9%
     * of the catalogue: listed but unpriced (new arrivals, pre-orders).
     * Treated as out of stock so the validator stops firing missing_price.
     */
    private static function cartPriceBlockIsEmpty(string $html): bool
    {
        if (preg_match(self::CART_PRICE_BLOCK_OPEN, $html, $m, PREG_OFFSET_CAPTURE) !== 1) {
            return false;
        }
        $window = substr(
            $html,
            $m[0][1] + strlen($m[0][0]),
            self::CART_PRICE_WINDOW
        );

        return preg_match(self::PRICE_CONTAINER, $window) !== 1
            && preg_match(self::PRICE, $window) !== 1;
    }

    // -------------------------------------------------------------- helpers

    /** @return array<string, string> label => value from the book-info block */
    private static function extractBookInfo(string $html): array
    {
        if (preg_match(self::BOOK_INFO_BLOCK, $html, $block) !== 1) {
            return [];
        }
        preg_match_all(self::BOOK_INFO_ROW, $block[1], $rows, PREG_SET_ORDER);

        $out = [];
        foreach ($rows as $row) {
            $label = trim(rtrim(trim(self::unescape($row[1]) ?? ''), ':'));
            $value = self::unescape($row[2]);
            if ($label !== '' && $value !== null) {
                $out[$label] = $value;
            }
        }

        return $out;
    }

    /**
     * Absolute product URL, or null when the href isn't a product.
     *
     * The `cntnt01page=N` query the CMSMS Products module echoes onto every
     * paginated card is stripped — the product is the same whichever result
     * page it appeared on.
     */
    private static function canonicalProductUrl(string $href): ?string
    {
        $clean = rtrim(trim(explode('#', explode('?', $href, 2)[0], 2)[0]), '/');
        if ($clean === '') {
            return null;
        }
        if (str_starts_with($clean, '//')) {
            $clean = 'https:' . $clean;
        } elseif (str_starts_with($clean, '/')) {
            $clean = self::BASE_URL . $clean;
        }

        return str_starts_with($clean, self::BASE_URL . '/produktas/') ? $clean : null;
    }

    private static function metaContent(string $html, string $property): ?string
    {
        $pattern = sprintf(
            '/<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']*)["\']/i',
            preg_quote($property, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

    /** `1 234,56 €` / `15.10 €` -> `1234.56`. */
    private static function parsePrice(?string $raw): ?string
    {
        if ($raw === null || preg_match(self::PRICE, $raw, $m) !== 1) {
            return null;
        }
        $value = str_replace([' ', ','], ['', '.'], $m[1]);

        return $value === '' ? null : $value;
    }

    private static function unescape(?string $value): ?string
    {
        if ($value === null) {
            return null;
        }
        $cleaned = html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $cleaned = trim(preg_replace('/\s+/u', ' ', $cleaned) ?? $cleaned);

        return $cleaned === '' ? null : $cleaned;
    }

    private static function intOrNull(?string $value): ?int
    {
        if ($value === null) {
            return null;
        }
        $trimmed = trim($value);

        return preg_match('/^-?\d+$/', $trimmed) === 1 ? (int) $trimmed : null;
    }
}
