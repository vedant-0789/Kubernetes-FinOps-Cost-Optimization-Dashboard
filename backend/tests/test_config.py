import pytest

from app.core.config import Settings


@pytest.mark.parametrize("raw,expected", [
    ("http://localhost:8080", ["http://localhost:8080"]),
    ("http://a.example.com, http://b.example.com", ["http://a.example.com", "http://b.example.com"]),
    ('["http://json.example.com"]', ["http://json.example.com"]),
])
def test_list_settings_accept_plain_csv_from_env(monkeypatch, raw, expected):
    """Regression: a plain FINOPS_CORS_ORIGINS (as in deploy/.env.example) crashed start-up."""
    monkeypatch.setenv("FINOPS_CORS_ORIGINS", raw)
    monkeypatch.setenv("FINOPS_PROTECTED_NAMESPACES", "kube-system,payments")
    s = Settings()
    assert s.cors_origins == expected
    assert s.protected_namespaces == ["kube-system", "payments"]
