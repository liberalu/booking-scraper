def test_get_scrape_activity_by_day_returns_list_of_correct_length(db_session):
    from book_scraper.dashboard.queries import get_scrape_activity_by_day

    result = get_scrape_activity_by_day(db_session, days=7)
    assert len(result) == 7
    assert all(isinstance(v, int) for v in result)
    assert all(v >= 0 for v in result)
