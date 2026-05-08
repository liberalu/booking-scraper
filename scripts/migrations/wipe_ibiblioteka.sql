BEGIN;

UPDATE scrape_runs
   SET status='failed', close_reason='superseded_by_canonical_layer'
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka')
   AND status IN ('running','paused');

DELETE FROM prices             WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM shop_book_changes  WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));

UPDATE discovered_urls SET shop_book_id = NULL
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');

UPDATE validation_issues SET shop_book_id = NULL
 WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));

DELETE FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');

DELETE FROM discovered_urls   WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_url_items  WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_run_events WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM validation_issues WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM cron_jobs         WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_runs       WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shop_settings     WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shops             WHERE name='ibiblioteka';

COMMIT;
