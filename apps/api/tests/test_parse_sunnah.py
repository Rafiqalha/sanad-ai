from sanad_core.providers.sunnah import parse_sunnah_reference


def test_parse_canonical_sunnah_ref():
    assert parse_sunnah_reference("https://sunnah.com/bukhari:1") == ("bukhari", "1")


def test_reject_non_sunnah_domain():
    assert parse_sunnah_reference("https://example.com/bukhari:1") is None


def test_reject_noncanonical_path():
    assert parse_sunnah_reference("https://sunnah.com/bukhari/1/1") is None


def test_reject_non_https_or_noncanonical_origin():
    assert parse_sunnah_reference("http://sunnah.com/bukhari:1") is None
    assert parse_sunnah_reference("https://user@sunnah.com/bukhari:1") is None
    assert parse_sunnah_reference("https://sunnah.com:8443/bukhari:1") is None
