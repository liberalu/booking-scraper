<?php

declare(strict_types=1);

namespace App\Services\Shops;

use App\Models\ShopBook;
use App\Repositories\ShopBookRepository;

final readonly class UnlinkCanonicalService
{
    public function __construct(private ShopBookRepository $shopBooks) {}

    /** @return array{shop_book_id: int, previous_book_id: int|null, changed: bool} */
    public function unlink(ShopBook $shopBook): array
    {
        $shopBookId = $shopBook->id;
        $previous = $shopBook->book_id;
        if ($previous === null) {
            return [
                'shop_book_id' => $shopBookId,
                'previous_book_id' => null,
                'changed' => false,
            ];
        }

        $this->shopBooks->unlinkCanonical($shopBook);

        return [
            'shop_book_id' => $shopBookId,
            'previous_book_id' => $previous,
            'changed' => true,
        ];
    }
}
