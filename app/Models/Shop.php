<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

/**
 * @property int $id
 * @property string $name
 * @property string $base_url
 * @property-read ScrapeRun|null $latestScrapeRun
 */
final class Shop extends Model
{
    protected $table = 'shops';

    public $timestamps = false;

    protected $fillable = ['name', 'base_url'];

    public function getRouteKeyName(): string
    {
        return 'name';
    }

    /** @return HasMany<ShopBook, $this> */
    public function shopBooks(): HasMany
    {
        return $this->hasMany(ShopBook::class, 'shop_id');
    }

    /** @return HasMany<DiscoveredUrl, $this> */
    public function discoveredUrls(): HasMany
    {
        return $this->hasMany(DiscoveredUrl::class, 'shop_id');
    }

    /** @return HasMany<ScrapeRun, $this> */
    public function scrapeRuns(): HasMany
    {
        return $this->hasMany(ScrapeRun::class, 'shop_id');
    }

    /** @return HasOne<ScrapeRun, $this> */
    public function latestScrapeRun(): HasOne
    {
        return $this->hasOne(ScrapeRun::class, 'shop_id')->latestOfMany('started_at');
    }
}
