<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * @property int $id
 * @property string $name
 * @property string $base_url
 */
final class Shop extends Model
{
    protected $table = 'shops';

    public $timestamps = false;

    protected $fillable = ['name', 'base_url'];

    public function shopBooks(): HasMany
    {
        return $this->hasMany(ShopBook::class, 'shop_id');
    }

    public function discoveredUrls(): HasMany
    {
        return $this->hasMany(DiscoveredUrl::class, 'shop_id');
    }

    public function scrapeRuns(): HasMany
    {
        return $this->hasMany(ScrapeRun::class, 'shop_id');
    }

    public static function byName(string $name): self
    {
        return self::where('name', $name)->firstOrFail();
    }
}
