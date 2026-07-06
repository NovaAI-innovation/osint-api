"""Happy-path tests for billing.main.verify_btcpay_sig."""
import hashlib
import hmac

from billing import main as billing_main

SECRET = "test_secret"


def _sign(payload, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_verify_btcpay_sig_valid():
    payload = b'{"invoiceId":"inv-1","status":"Settled"}'
    assert billing_main.verify_btcpay_sig(payload, _sign(payload), SECRET) is True


def test_verify_btcpay_sig_rejects_bad_signature():
    assert billing_main.verify_btcpay_sig(b"abc", "sha256=deadbeef", SECRET) is False


def test_verify_btcpay_sig_rejects_missing_prefix():
    assert billing_main.verify_btcpay_sig(b"abc", "plainhex", SECRET) is False


def test_verify_btcpay_sig_rejects_empty_signature():
    assert billing_main.verify_btcpay_sig(b"abc", "", SECRET) is False


def test_verify_btcpay_sig_different_secret_rejects():
    payload = b"abc"
    sig = _sign(payload, secret="other_secret")
    assert billing_main.verify_btcpay_sig(payload, sig, SECRET) is False
