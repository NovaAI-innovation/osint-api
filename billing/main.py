import os
import hmac
import hashlib
import logging
from typing import Optional

from fastapi import FastAPI, Request, Header, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import get_db, SessionLocal, Invoice, UserCredits

# --- Configuration ---
# In production, load from environment variables or Vault
BTCPAY_SECRET = os.getenv("BTCPAY_WEBHOOK_SECRET", "test_secret")
PAYPAL_CERT_URL = os.getenv("PAYPAL_CERT_URL", "https://api.paypal.com/v1/notifications/public-keys")

app = FastAPI(title="OSINT Billing Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helpers ---

def verify_btcpay_sig(payload: bytes, sig_header: str, secret: str) -> bool:
    """
    Verify BTCPay Server HMAC SHA256 signature.
    """
    if not sig_header:
        return False
    
    # BTCPay sends signature as sha256=...
    expected_prefix = "sha256="
    if not sig_header.startswith(expected_prefix):
        return False
    
    # Compute hash
    mac = hmac.new(secret.encode('utf-8'), msg=payload, digestmod=hashlib.sha256)
    computed_sig = expected_prefix + mac.hexdigest()
    
    # Constant time comparison to prevent timing attacks
    return hmac.compare_digest(computed_sig, sig_header)

# --- Endpoints ---

@app.post("/webhooks/btcpay")
async def btcpay_webhook(
    request: Request, 
    btcpay_sig: Optional[str] = Header(None, alias="BTCPay-Sig")
):
    """
    Handles BTCPay Server webhooks.
    1. Verify HMAC Signature
    2. Parse Invoice ID
    3. Update DB (Invoice status + Credits)
    """
    payload = await request.body()
    
    # 1. Security: Verify Signature
    if not verify_btcpay_sig(payload, btcpay_sig, BTCPAY_SECRET):
        logger.warning("Invalid BTCPay signature received.")
        raise HTTPException(status_code=403, detail="Invalid Signature")
    
    try:
        data = await request.json()
    except Exception:
        logger.error("Failed to parse BTCPay JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # 2. Extract Data
    # BTCPay payload structure: { "invoiceId": "...", "status": "Settled", ... }
    invoice_id = data.get("invoiceId")
    invoice_status = data.get("status")
    
    if not invoice_id or not invoice_status:
        logger.warning("Missing invoiceId or status in BTCPay webhook")
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # We only care about Settled (confirmed) invoices for credits
    if invoice_status.lower() != "settled":
        return {"status": "ignored", "reason": "Invoice not settled"}

    db = SessionLocal()
    try:
        # 3. Find Invoice in DB
        # Note: In a real flow, Gateway creates the invoice on BTCPay and stores BTCPay's ID in `external_ref`
        invoice = db.query(Invoice).filter(Invoice.external_ref == invoice_id).first()
        
        if not invoice:
            logger.warning(f"Invoice not found for external_ref: {invoice_id}")
            return {"status": "ignored", "reason": "Invoice not found"}
        
        if invoice.status == "completed":
            logger.info(f"Invoice {invoice.id} already processed.")
            return {"status": "success", "message": "Idempotency: Already processed"}
        
        # 4. Update Invoice and Add Credits
        invoice.status = "completed"
        
        user_credits = db.query(UserCredits).filter(UserCredits.user_id == invoice.user_id).first()
        if user_credits:
            user_credits.balance += invoice.credits_purchased
        else:
            # Should exist due to FK, but handle gracefully
            logger.error(f"Credits record not found for user {invoice.user_id}")
            raise HTTPException(status_code=500, detail="Internal Error")
            
        db.commit()
        logger.info(f"Successfully processed payment for Invoice {invoice.id}. Added {invoice.credits_purchased} credits.")
        
        return {"status": "success", "invoice_id": str(invoice.id)}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing BTCPay webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        db.close()

@app.post("/webhooks/paypal")
async def paypal_webhook(
    request: Request,
    paypal_auth_algo: Optional[str] = Header(None, alias="PayPal-Auth-Algo"),
    paypal_transmission_sig: Optional[str] = Header(None, alias="PayPal-Transmission-Sig"),
    paypal_cert_id: Optional[str] = Header(None, alias="PayPal-Cert-Id")
):
    """
    Handles PayPal IPN/Webhooks.
    Note: Full PayPal signature verification involves fetching certs from PayPal API.
    This is a simplified implementation of the logic flow.
    """
    
    # 1. Security: Verify Headers exist
    if not all([paypal_auth_algo, paypal_transmission_sig, paypal_cert_id]):
        logger.warning("Missing PayPal security headers")
        raise HTTPException(status_code=403, detail="Missing Security Headers")
    
    # In production: Fetch cert from PAYPAL_CERT_URL using paypal_cert_id
    # Verify signature against payload using the cert
    # cert = fetch_paypal_cert(paypal_cert_id)
    # if not verify_paypal_sig(payload, cert, paypal_transmission_sig, paypal_auth_algo):
    #    raise HTTPException(403)
    
    # 2. Parse Payload
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # PayPal structure varies, typically resource -> id for invoice/order
    resource = data.get("resource", {})
    event_type = data.get("event_type")
    
    # We look for PAYMENT.CAPTURE.COMPLETED or similar
    if event_type not in ["PAYMENT.CAPTURE.COMPLETED", "INVOICE.PAID"]:
        return {"status": "ignored", "reason": "Event not relevant"}
    
    external_ref = resource.get("id") # The PayPal Invoice/Order ID
    if not external_ref:
        raise HTTPException(status_code=400, detail="Missing Resource ID")

    db = SessionLocal()
    try:
        # 3. Lookup and Update
        invoice = db.query(Invoice).filter(Invoice.external_ref == external_ref).first()
        
        if not invoice:
            return {"status": "ignored", "reason": "Invoice not found"}
        
        if invoice.status == "completed":
            return {"status": "success", "message": "Idempotency: Already processed"}
        
        invoice.status = "completed"
        
        user_credits = db.query(UserCredits).filter(UserCredits.user_id == invoice.user_id).first()
        if user_credits:
            user_credits.balance += invoice.credits_purchased
        else:
            raise HTTPException(status_code=500, detail="Internal Error")
            
        db.commit()
        logger.info(f"Successfully processed PayPal payment for Invoice {invoice.id}.")
        
        return {"status": "success", "invoice_id": str(invoice.id)}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing PayPal webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
