from __future__ import annotations
import os, json, uuid
from datetime import datetime
from typing import Dict, Any

from src.config import CFG


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _load_payment_info() -> Dict[str, Any]:
    path = os.path.join(CFG.data_dir, "mock_payment.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass

def _mask_card(payment: Dict[str, Any]) -> Dict[str, Any]:
    pan = str(payment.get("card_number", ""))
    last4 = pan[-4:] if len(pan) >= 4 else "0000"
    return {
        "cardholder_name": payment.get("cardholder_name", "Demo User"),
        "network": payment.get("network", "Card"),
        "last4": last4,
        "exp_month": int(payment.get("exp_month", 12) or 12),
        "exp_year": int(payment.get("exp_year", 2030) or 2030),
        "billing_address": payment.get("billing_address", {}),
    }


def book_and_write_receipt(
    booking_dir: str,
    trip_request: Dict[str, Any],
    itinerary_text: str,
    flight_option: Dict[str, Any],
    hotel_option: Dict[str, Any],
    total_price_usd: float,
) -> str:

    os.makedirs(booking_dir, exist_ok=True)

    flight_booking_id = _gen_id("FL")
    hotel_booking_id  = _gen_id("HT")
    booking_id = _gen_id("BOOK")

    payment_raw = _load_payment_info()
    payment_masked = _mask_card(payment_raw)

    charge = {
        "charge_id": _gen_id("CHG"),
        "status": "succeeded",            # always succeeds in this PoC
        "authorized_at": _now_iso(),
        "amount_usd": float(total_price_usd or 0.0),
        "currency": "USD",
    }

    payload: Dict[str, Any] = {
        "booking_id": booking_id,
        "created_at": _now_iso(),
        "trip_request": trip_request,
        "itinerary_markdown": itinerary_text,
        "flight_option": flight_option,
        "hotel_option": hotel_option,
        "total_price_usd": float(total_price_usd or 0.0),
        "flight_booking_id": flight_booking_id,
        "hotel_booking_id": hotel_booking_id,
        "billing": {
            "payment_method": payment_masked,   
            "charge": charge                    
        },
    }

    out_path = os.path.join(booking_dir, f"{booking_id}.json")
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    return out_path
