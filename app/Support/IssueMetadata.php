<?php

declare(strict_types=1);

namespace App\Support;

final class IssueMetadata
{
    public const array SEVERITY = [
        'active_no_price' => 'critical',
        'attribute_invalid_value' => 'warning',
        'attribute_unknown_key' => 'warning',
        'book_no_metadata' => 'warning',
        'book_no_signals' => 'info',
        'discover_fetch_failed' => 'warning',
        'empty_response' => 'warning',
        'field_cleared' => 'critical',
        'format_is_dimensions' => 'info',
        'format_mismatch' => 'warning',
        'html_in_text' => 'warning',
        'in_stock_no_price' => 'critical',
        'invalid_isbn' => 'warning',
        'invalid_price' => 'critical',
        'invalid_price_original' => 'critical',
        'invalid_year' => 'warning',
        'isbn_duplicate' => 'warning',
        'match_isbn_drift' => 'warning',
        'missing_price' => 'critical',
        'missing_title' => 'critical',
        'no_price_history' => 'warning',
        'non_book_has_isbn' => 'warning',
        'non_product_active' => 'info',
        'orphan_no_url' => 'info',
        'price_higher_than_original' => 'critical',
        'price_zero' => 'critical',
        'product_url_non_book' => 'info',
        'scrape_run_failed' => 'critical',
        'slug_diacritic_loss' => 'info',
        'slug_title_mismatch' => 'info',
        'stale_active' => 'warning',
        'suspicious_title' => 'warning',
        'title_author_duplicate' => 'warning',
        'unmatched_has_isbn' => 'info',
        'unreachable_active' => 'warning',
        'url_aliases' => 'info',
        'year_out_of_range' => 'warning',
        'year_pages_swap' => 'warning',
        'zero_price' => 'critical',
    ];

    public const array DESCRIPTIONS = [
        'active_no_price' => 'Book is marked active but has no price on record. The pricing element may have moved or the product was unpublished from the shop.',
        'attribute_invalid_value' => 'A property value doesn\'t match the allowed enum or regex in the shop config.',
        'attribute_unknown_key' => 'A property key not in the shop\'s allowed attribute list. Add to config or fix the parser.',
        'book_no_metadata' => 'Book is classified as a book but is missing key metadata (ISBN, year, or author). Parser may be too permissive — check the classification logic.',
        'book_no_signals' => 'Book has no features that classify it as a book (no ISBN, no author, format is not a binding type). May be a non-book product that slipped through classification.',
        'discover_fetch_failed' => 'Category or sitemap page returned an error or timed out during URL discovery. Transient network issues or a shop-side block.',
        'empty_response' => 'The product page returned an empty body (HTTP 200 but no content). FlareSolverr may have timed out, or the shop serves an empty page for bot traffic.',
        'field_cleared' => 'A field that had a value is now missing. Likely a parser regression.',
        'format_is_dimensions' => 'Format field contains what looks like physical dimensions (e.g. \'210×297 mm\') rather than a binding type. The parser is reading the wrong attribute.',
        'format_mismatch' => 'Format inconsistent with metadata — e.g. audiobook has pages, hardcover has duration.',
        'html_in_text' => 'HTML tags found in title or author. Raw markup leaked into a text field.',
        'in_stock_no_price' => 'Book is marked in-stock but has no current price. The price may have been removed or the stock/price selectors are misaligned.',
        'invalid_isbn' => 'The scraped ISBN-13 value fails the standard Luhn/check-digit validation or has the wrong digit count. Often an EAN-13 barcode picked up instead of the book\'s ISBN.',
        'invalid_price' => 'Price couldn\'t be parsed as a number. Item was dropped.',
        'invalid_price_original' => 'Original price couldn\'t be parsed. Stored as null.',
        'invalid_year' => 'Publication year is outside the plausible range (before 1400 or in the future). Parser may be selecting a wrong numeric element.',
        'isbn_duplicate' => 'Two or more shop books share the same ISBN-13. One is likely a data entry error or a reprinted edition. Check both entries and merge or correct.',
        'match_isbn_drift' => 'The shop_book ISBN doesn\'t match any ISBN on its linked canonical book. Either the shop_book ISBN got corrupted (re-scrape the URL to refresh it) or the canonical link is wrong (unlink book_id and run match again).',
        'missing_price' => 'No price scraped. Parser likely hit a broken or restructured product page.',
        'missing_title' => 'No title scraped. Item was dropped.',
        'no_price_history' => 'No price has ever been recorded for this book. It may never have been successfully scraped, or was discovered but never scanned.',
        'non_book_has_isbn' => 'Item classified as non-book but carries an ISBN-13. Re-examine the classification — it is likely a book.',
        'non_product_active' => 'A URL classified as non-product is still marked active. Either the classifier is wrong or the URL changed purpose.',
        'orphan_no_url' => 'Shop book record exists but has no linked discovered_url. This can happen if the URL was deleted from discovered_urls or was never discovered.',
        'price_higher_than_original' => 'Sale price exceeds the original. Likely a data inversion — original and current fields may be swapped.',
        'price_zero' => 'Price scraped as 0.00. Parser probably matched an empty or placeholder element. Same as zero_price — check parser selectors.',
        'product_url_non_book' => 'A URL classified as a product page but the shop book at that URL is classified as non-book. The product exists but is not a book — review classification.',
        'scrape_run_failed' => 'A scrape run ended with status=failed. Inspect the run\'s detail page to see why (stall, kill, orphan on boot, or downstream error).',
        'slug_diacritic_loss' => 'The URL slug looks like the shop\'s slug generator dropped Lithuanian diacritic characters entirely (e.g. \'Kalėdų pūga\' → \'kale-du-pu-ga\') instead of transliterating them (expected \'kaledu-puga\'). A shop-side bug — worth reporting to the shop to improve their product URLs.',
        'slug_title_mismatch' => 'The URL slug and the scraped title diverge significantly. The parser may be picking up a wrong title element, or the shop renamed the product without updating the slug.',
        'stale_active' => 'Book is marked active but was last seen in a scrape run over 30 days ago. It may have been silently delisted.',
        'suspicious_title' => 'Title shorter than 2 chars or longer than 300. Parser may be selecting the wrong element.',
        'title_author_duplicate' => 'Two or more shop books share the exact title and author. Could be duplicate data entry or a multi-format edition (print/ebook) that should be a single record.',
        'unmatched_has_isbn' => 'Book has a valid ISBN but no canonical book match. Either the match phase has not run yet or the ISBN is not in the canonical catalogue.',
        'unreachable_active' => 'Book is marked active but the URL consistently returns 404, 410, or connection error. The product has likely been removed.',
        'url_aliases' => 'Multiple distinct URLs resolve to the same product (e.g. via redirects or slug variants). The shop may serve the same page under multiple paths.',
        'year_out_of_range' => 'Publication year is before 1400 or in the future. The parser is likely picking up a wrong numeric element (e.g. page count or product ID).',
        'year_pages_swap' => 'Year and page-count appear to be swapped — e.g. year=312 and pages=2024. Check the parser\'s attribute extraction order.',
        'zero_price' => 'Price parsed as 0.00. Parser probably matched an empty or wrong element.',
    ];

    public static function severity(string $issue): string
    {
        return self::SEVERITY[$issue] ?? 'warning';
    }

    public static function description(string $issue): string
    {
        return self::DESCRIPTIONS[$issue] ?? '';
    }

    /** @return list<string> */
    public static function typesWithSeverity(string $severity): array
    {
        return array_keys(array_filter(
            self::SEVERITY,
            static fn (string $value): bool => $value === $severity
        ));
    }
}
