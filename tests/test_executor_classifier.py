from app.executor import NodeExecutor


def test_page_classifier_distinguishes_key_states():
    classify = NodeExecutor._classify_page
    assert classify(200, "<title>ChatGPT</title>", True, "target") == "available"
    assert classify(200, "Sign in to continue", False, "login") == "login_required"
    assert classify(403, "Just a moment cf-chl-", False, "target") == "available"
    assert (
        classify(451, "Not available in your country", False, "target")
        == "region_blocked"
    )
    assert classify(503, "maintenance", False, "target") == "service_error"
    assert classify(403, "Access denied", False, "target") == "service_blocked"
    assert classify(200, "unexpected body", False, "target") == "uncertain"
    assert classify(418, "unexpected body", False, "target") == "response_error"


def test_curl_error_classifier():
    classify = NodeExecutor._curl_error_type
    assert classify(6, 0) == "dns_error"
    assert classify(7, 0) == "tcp_error"
    assert classify(28, 0) == "timeout"
    assert classify(60, 1) == "tls_error"
    assert classify(97, 0) == "proxy_error"
