import pytest

from kartcv import http


def test_malformed_urls_raise_oserror():  # review I3: callers only need to catch OSError
    with pytest.raises(OSError):
        http.get("not-a-url", {})
    with pytest.raises(OSError):
        http.post_json("not-a-url", {}, {})
