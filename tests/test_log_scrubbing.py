from src.utils.logger import _scrub_sensitive


def test_scrub_sensitive_redacts_query_params():
    url = "https://maps.googleapis.com/maps/api/distancematrix/json?origins=1,2&key=SECRET&language=es"
    scrubbed = _scrub_sensitive(url)
    assert "key=[REDACTED]" in scrubbed
    assert "SECRET" not in scrubbed


def test_scrub_sensitive_redacts_authorization_header():
    payload = {"headers": {"Authorization": "Bearer SECRET"}, "url": "https://example.com/?token=SECRET"}
    scrubbed = _scrub_sensitive(payload)
    assert scrubbed["headers"]["Authorization"] == "[REDACTED]"
    assert "token=[REDACTED]" in scrubbed["url"]

