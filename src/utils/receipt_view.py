from pathlib import Path
from typing import List

def _get(d: dict, keys: List[str], default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def _fmt_money(x) -> str:
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "—"

def _fmt_rating(x) -> str:
    try:
        v = float(x)
        return f"{v:.1f}/10" if v <= 10 else f"{v:.1f}★"
    except Exception:
        return "—"

def render_booking_markdown(data: dict, file_path: str) -> str:
    tr  = data.get("trip_request", {}) or {}
    fo  = data.get("flight_option", {}) or {}
    ho  = data.get("hotel_option", {}) or {}
    bil = data.get("billing", {}) or {}

    origin = tr.get("origin") or "?"
    dest   = tr.get("destination") or "?"
    start  = tr.get("start_date") or "?"
    days   = tr.get("days") or "?"
    budget = tr.get("budget")
    nights = max(1, int(days) - 1) if isinstance(days, int) else None

    o = fo.get("outbound") or {}
    r = fo.get("return")   or {}

    o_from = _get(o, ["departure_city","origin","from","depart_city"], "?")
    o_to   = _get(o, ["arrival_city","destination","to","arrive_city"], "?")
    o_date = _get(o, ["departure_date","date","flight_date","depart_date"], "")
    o_time = _get(o, ["departure_time","time","depart_time"], "")
    o_air  = _get(o, ["airline","carrier"], "")
    o_num  = _get(o, ["flight_number","number","flight_no"], "")

    r_from = _get(r, ["departure_city","origin","from","depart_city"], "?")
    r_to   = _get(r, ["arrival_city","destination","to","arrive_city"], "?")
    r_date = _get(r, ["departure_date","date","flight_date","depart_date"], "")
    r_time = _get(r, ["departure_time","time","depart_time"], "")
    r_air  = _get(r, ["airline","carrier"], "")
    r_num  = _get(r, ["flight_number","number","flight_no"], "")

    roundtrip_total = fo.get("roundtrip_price_usd")

    hotel_name = _get(ho, ["hotel_name","name"], "—")
    hotel_city = _get(ho, ["city","destination","location"], "")
    room_type  = _get(ho, ["room_type","room","room_name"], "")
    nightly    = _get(ho, ["price_per_night_usd","price_usd","nightly_usd","_nightly"])
    rating     = _get(ho, ["rating_out_of_10","star_rating","stars"])
    hotel_total = nightly * nights if (isinstance(nightly,(int,float)) and isinstance(nights,int)) else None

    pm = bil.get("payment_method", {}) or {}
    ch = bil.get("charge", {}) or {}
    last4   = pm.get("last4","????")
    network = pm.get("network","Card")
    exp_m   = pm.get("exp_month","—")
    exp_y   = pm.get("exp_year","—")
    charge_status = ch.get("status","—")
    charge_id     = ch.get("charge_id","—")
    charge_amt    = ch.get("amount_usd")
    total         = data.get("total_price_usd")

    md = []
    md.append(f"**Created:** {data.get('created_at','')}  \n**Booking ID:** `{data.get('booking_id','')}`")
    md.append("---")
    md.append("### 🧭 Trip")
    md.append(f"- **Route:** {origin} → {dest}")
    md.append(f"- **Start:** {start}   •   **Days:** {days}   •   **Nights:** {nights if nights is not None else '—'}")
    md.append(f"- **Budget:** {_fmt_money(budget)}" if budget is not None else "- **Budget:** —")

    md.append("\n### ✈️ Flights")
    md.append(f"- **Outbound:** {o_from} → {o_to}  •  {o_date} {o_time}  •  {o_air} {o_num}".rstrip())
    md.append(f"- **Return:** {r_from} → {r_to}  •  {r_date} {r_time}  •  {r_air} {r_num}".rstrip())
    md.append(f"- **Roundtrip total:** {_fmt_money(roundtrip_total)}")

    md.append("\n### 🏨 Hotel")
    md.append(f"- **{hotel_name}** — {hotel_city}  •  {room_type}  •  rating: {_fmt_rating(rating)}")
    if nightly is not None and nights is not None:
        md.append(f"- **{nights} nights × {_fmt_money(nightly)} = {_fmt_money(hotel_total)}**")
    else:
        md.append(f"- **Total:** {_fmt_money(hotel_total)}")

    md.append("\n### 💳 Billing")
    md.append(f"- **Card:** {network} •••• {last4}  (exp {exp_m}/{exp_y})")
    md.append(f"- **Charge:** {charge_status} • `{charge_id}` • {_fmt_money(charge_amt)}")

    md.append(f"\n### 💰 Grand Total: **{_fmt_money(total)}**")
    md.append("---")
    md.append(f"[Download JSON]({Path(file_path).as_posix()})")
    return "\n".join(md)