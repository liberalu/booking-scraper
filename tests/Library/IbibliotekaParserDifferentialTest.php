<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Ibiblioteka\Parser;
use PHPUnit\Framework\TestCase;

final class IbibliotekaParserDifferentialTest extends TestCase
{
    private const FIXTURES = __DIR__.'/../fixtures/ibiblioteka';

    private const GOLDEN = __DIR__.'/../golden';

    public function test_search_response_matches_python(): void
    {
        $this->assertMatchesGolden(
            'ibiblioteka_search',
            Parser::parseSearchResponse(self::fixture('search_response.json'))
        );
    }

    public function test_translated_book_detail_matches_python(): void
    {
        $this->assertMatchesGolden(
            'ibiblioteka_translated',
            Parser::parseProductPage(self::fixture('product_detail_translated.json'))
        );
    }

    public function test_audiobook_detail_matches_python(): void
    {
        $this->assertMatchesGolden(
            'ibiblioteka_audio',
            Parser::parseProductPage(self::fixture('product_detail_audio.json'))
        );
    }

    public function test_scan_url_rewrite_matches_python(): void
    {
        $golden = json_decode(
            (string) file_get_contents(self::GOLDEN.'/ibiblioteka_rewrite.json'),
            true,
            flags: JSON_THROW_ON_ERROR
        );
        foreach ($golden as $case) {
            self::assertSame(
                self::sorted($case['result']),
                self::sorted(Parser::rewriteScanUrl($case['url'])),
                "rewriteScanUrl diverged for {$case['url']}"
            );
        }
    }

    public function test_category_page_is_an_alias_for_the_search_response(): void
    {

        self::assertSame(
            Parser::parseSearchResponse(self::fixture('search_response.json')),
            Parser::parseCategoryPage(self::fixture('search_response.json'))
        );
    }

    public function test_records_are_tagged_for_the_canonical_branch(): void
    {

        $result = Parser::parseProductPage(self::fixture('product_detail_translated.json'));

        self::assertSame('book', $result['_emit_as']);
        self::assertSame('ibiblioteka', $result['data_source']);
        self::assertTrue($result['is_book_product']);
        self::assertArrayNotHasKey('price', $result);
    }

    public function test_electronic_with_an_audio_description_is_audio(): void
    {

        $result = Parser::parseProductPage(json_encode([
            'publicationFormat' => 'ELECTRONIC',
            'allPhysicalAttributes' => '1 mp3 failas (9 val., 25 min.)',
        ]));

        self::assertSame('audio', $result['type']);
        self::assertNull($result['pages'], 'an audiobook must not carry a page count');
        self::assertNotNull($result['duration']);
    }

    public function test_electronic_without_audio_hints_is_an_ebook(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'publicationFormat' => 'ELECTRONIC',
            'allPhysicalAttributes' => '1 elektroninis failas',
        ]));

        self::assertSame('ebook', $result['type']);
    }

    public function test_printed_binding_is_read_from_the_physical_description(): void
    {
        foreach ([
            '312 p. : kietais viršeliais' => 'book',
            '288 p. : minkštais viršeliais' => 'book',
            '200 p.' => 'book',
        ] as $physical => $expectedType) {
            $result = Parser::parseProductPage(json_encode([
                'publicationFormat' => 'PRINTED',
                'allPhysicalAttributes' => $physical,
            ]));

            self::assertSame($expectedType, $result['type']);
        }
    }

    public function test_page_count_and_dimensions_come_out_of_one_field(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'publicationFormat' => 'PRINTED',
            'allPhysicalAttributes' => '312 p. : iliustr. ; 21 cm',
        ]));

        self::assertSame(312, $result['pages']);
        self::assertSame('21 cm', $result['dimensions']);
    }

    public function test_multipart_works_expose_their_volume_urls(): void
    {

        $result = Parser::parseProductPage(json_encode([
            'code' => 'C1B0000814700',
            'multipart' => true,
            'parts' => [['code' => 'C1B0000814701'], ['code' => 'C1B0000814702']],
        ]));

        self::assertSame([
            'https://ibiblioteka.lt/metis-api/bibliographic-records/public/C1B0000814701',
            'https://ibiblioteka.lt/metis-api/bibliographic-records/public/C1B0000814702',
        ], $result['_part_urls']);
    }

    public function test_a_single_part_record_exposes_no_volume_urls(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'code' => 'C1B0000814700',
            'multipart' => false,
            'parts' => [['code' => 'ignored']],
        ]));

        self::assertSame([], $result['_part_urls']);
    }

    public function test_contributors_get_a_role_and_a_per_role_position(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'authorViews' => [['value' => 'Primary Author', 'code' => 'A1']],
            'persons' => [
                ['name' => 'A Translator', 'code' => 'T1', 'types' => [['code' => '730']]],
                ['name' => 'A Narrator', 'code' => 'N1', 'types' => [['code' => '550']]],
            ],
        ]));

        self::assertSame([
            ['name' => 'Primary Author', 'libis_code' => 'A1', 'role' => 'author', 'position' => 0],
            ['name' => 'A Translator', 'libis_code' => 'T1', 'role' => 'translator', 'position' => 0],
            ['name' => 'A Narrator', 'libis_code' => 'N1', 'role' => 'narrator', 'position' => 0],
        ], $result['authors']);
    }

    public function test_the_renamed_titlelt_name_field_is_read(): void
    {

        $result = Parser::parseProductPage(json_encode([
            'authorViews' => [['titleLt' => 'Maceina, Antanas', 'code' => 'A1']],
            'persons' => [
                ['titleLt' => 'Karpauskaite, Gabija', 'code' => 'T1', 'types' => [['code' => '730']]],
            ],
        ]));

        self::assertSame([
            ['name' => 'Maceina, Antanas', 'libis_code' => 'A1', 'role' => 'author', 'position' => 0],
            ['name' => 'Karpauskaite, Gabija', 'libis_code' => 'T1', 'role' => 'translator', 'position' => 0],
        ], $result['authors']);
    }

    public function test_a_person_listed_twice_in_one_role_appears_once(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'authorViews' => [['value' => 'Same Person', 'code' => 'P1']],
            'persons' => [
                ['name' => 'Same Person', 'code' => 'P1', 'types' => [['code' => '070']]],
            ],
        ]));

        self::assertCount(1, $result['authors']);
    }

    public function test_unknown_role_codes_are_ignored(): void
    {
        $result = Parser::parseProductPage(json_encode([
            'persons' => [
                ['name' => 'Mystery Role', 'code' => 'X1', 'types' => [['code' => '999']]],
            ],
        ]));

        self::assertSame([], $result['authors']);
    }

    public function test_publisher_and_year_are_split_out_of_publication_view(): void
    {
        $result = Parser::parseSearchResponse(json_encode([
            'results' => ['content' => [[
                'id' => 1,
                'titleView' => 'A Book',
                'publicationView' => 'Vilnius : Alma littera, 2022',
            ]]],
        ]));

        $product = $result['products'][0];
        self::assertSame(2022, $product['year']);
        self::assertSame('Alma littera', $product['publisher']);
    }

    public function test_a_publication_view_without_a_colon_yields_no_publisher(): void
    {
        $result = Parser::parseSearchResponse(json_encode([
            'results' => ['content' => [[
                'id' => 1, 'titleView' => 'A Book', 'publicationView' => '2022',
            ]]],
        ]));

        self::assertSame(2022, $result['products'][0]['year']);
        self::assertNull($result['products'][0]['publisher']);
    }

    public function test_records_without_an_id_are_skipped(): void
    {

        $result = Parser::parseSearchResponse(json_encode([
            'results' => ['content' => [
                ['titleView' => 'No id'],
                ['id' => 7, 'titleView' => 'Has id'],
            ]],
        ]));

        self::assertCount(1, $result['products']);
        self::assertStringEndsWith('/7', $result['products'][0]['url']);
    }

    public function test_malformed_json_yields_empty_results(): void
    {
        self::assertSame(['products' => [], 'total' => null], Parser::parseSearchResponse('nope'));

        $empty = Parser::parseProductPage('nope');
        self::assertFalse($empty['is_book_product']);
        self::assertNull($empty['title']);
    }

    private function assertMatchesGolden(string $name, mixed $actual): void
    {
        $golden = json_decode(
            (string) file_get_contents(self::GOLDEN."/{$name}.json"),
            true,
            flags: JSON_THROW_ON_ERROR
        );

        self::assertSame(self::sorted($golden), self::sorted($actual));
    }

    private static function sorted(mixed $value): mixed
    {
        if (! is_array($value)) {
            return $value;
        }
        $value = array_map([self::class, 'sorted'], $value);
        if (! array_is_list($value)) {
            ksort($value);
        }

        return $value;
    }

    private static function fixture(string $name): string
    {
        return (string) file_get_contents(self::FIXTURES.'/'.$name);
    }
}
