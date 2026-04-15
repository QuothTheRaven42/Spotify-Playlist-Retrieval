from main import ms_to_time

def test_ms_to_time():
    assert ms_to_time(259000) == "04:19"
    assert ms_to_time(0) == "00:00"
    assert ms_to_time(61000) == "01:01"