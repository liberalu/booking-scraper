<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Models\Shop;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Operator actions on the issues inbox.
 *
 * All of these are pure database writes — no crawl is spawned — so they
 * behave identically in either stack.
 */
final class IssueMutationsController
{
    private const LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    /** The only snooze durations the UI offers. */
    private const SNOOZE_DAYS = [7, 30, 90];

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function lifecycle(Request $request, int $issueId): mixed
    {
        $state = (string) $request->query('state', '');
        if (!in_array($state, self::LIFECYCLE_STATES, true)) {
            return response()->json([
                'detail' => "state must be one of {'" . implode("', '", self::LIFECYCLE_STATES) . "'}",
            ], 400);
        }

        $issue = DB::table('validation_issues')->where('id', $issueId)->first();
        if ($issue === null) {
            return response()->json(['detail' => 'Issue not found'], 404);
        }

        DB::table('validation_issues')->where('id', $issueId)->update([
            'lifecycle_state' => $state,
            // Cleared on any other transition, so a re-acknowledgement gets a
            // fresh timestamp rather than the original one.
            'acknowledged_at' => $state === 'acknowledged' ? Carbon::now('UTC') : null,
        ]);

        return ['id' => $issueId, 'lifecycle_state' => $state];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function snooze(Request $request, int $issueId): mixed
    {
        $days = (int) ($request->input('days') ?: 7);
        if (!in_array($days, self::SNOOZE_DAYS, true)) {
            return response()->json(['detail' => 'days must be 7, 30, or 90'], 422);
        }

        $until = Carbon::now('UTC')->addDays($days);
        $updated = DB::table('validation_issues')->where('id', $issueId)->update([
            'lifecycle_state' => 'snoozed',
            'snoozed_until' => $until,
        ]);

        if ($updated === 0) {
            return response()->json(['detail' => 'Issue not found'], 404);
        }

        return ['snoozed_until' => self::iso($until), 'days' => $days];
    }

    /**
     * Acknowledge every `new` issue of a type, optionally within one shop.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function bulkAcknowledge(Request $request): mixed
    {
        $issueType = (string) ($request->input('issue_type') ?: '');
        if ($issueType === '') {
            return response()->json(['detail' => 'issue_type is required'], 422);
        }

        $query = DB::table('validation_issues')
            ->where('issue', $issueType)
            ->where('lifecycle_state', 'new');

        $shopId = self::shopId($request);
        if ($shopId !== null) {
            $query->where('shop_id', $shopId);
        }

        return ['acknowledged' => $query->update([
            'lifecycle_state' => 'acknowledged',
            'acknowledged_at' => Carbon::now('UTC'),
        ])];
    }

    /**
     * Undo a bulk acknowledge.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function bulkUnacknowledge(Request $request): mixed
    {
        $issueType = (string) ($request->input('issue_type') ?: '');
        if ($issueType === '') {
            return response()->json(['detail' => 'issue_type is required'], 422);
        }

        $query = DB::table('validation_issues')
            ->where('issue', $issueType)
            ->where('lifecycle_state', 'acknowledged');

        $shopId = self::shopId($request);
        if ($shopId !== null) {
            $query->where('shop_id', $shopId);
        }

        return ['unacknowledged' => $query->update([
            'lifecycle_state' => 'new',
            'acknowledged_at' => null,
        ])];
    }

    /**
     * Collect the product URLs behind every open issue of a type.
     *
     * Returns them rather than spawning: the caller posts them to /runs as a
     * targeted scan, which goes through the single-URL rescrape path instead
     * of the pending queue (that queue is bound to historical run ids).
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function bulkRescrape(Request $request): mixed
    {
        $issueType = (string) ($request->input('issue_type') ?: '');
        if ($issueType === '') {
            return response()->json(['detail' => 'issue_type is required'], 422);
        }
        $shopName = (string) ($request->input('shop') ?: '');
        if ($shopName === '') {
            return response()->json(['detail' => 'shop is required'], 422);
        }
        $shopId = Shop::where('name', $shopName)->value('id');
        if ($shopId === null) {
            return response()->json(['detail' => "Unknown shop: {$shopName}"], 404);
        }

        $urls = DB::table('discovered_urls as du')
            ->join('shop_books as sb', 'sb.id', '=', 'du.shop_book_id')
            ->join('validation_issues as vi', 'vi.shop_book_id', '=', 'sb.id')
            ->where('du.url_type', 'product')
            ->where('vi.shop_id', $shopId)
            ->where('vi.issue', $issueType)
            ->whereIn('vi.lifecycle_state', ['new', 'acknowledged'])
            ->distinct()
            ->orderBy('du.url')
            ->pluck('du.url')
            ->filter()
            ->values()
            ->all();

        return ['urls' => implode(',', $urls), 'count' => count($urls)];
    }

    /**
     * An unknown shop name yields null, which leaves the action unscoped —
     * matching Python rather than silently matching nothing.
     */
    private static function shopId(Request $request): ?int
    {
        $name = (string) ($request->input('shop') ?: '');
        if ($name === '') {
            return null;
        }
        $id = Shop::where('name', $name)->value('id');

        return $id !== null ? (int) $id : null;
    }

    private static function iso(Carbon $dt): string
    {
        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }
}
