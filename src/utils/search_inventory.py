from __future__ import annotations
import os
from typing import Optional, Dict, Any, Tuple, List

import pandas as pd
from datetime import datetime, timedelta
import bisect

def load_data(data_dir: str = "data") -> tuple[pd.DataFrame, pd.DataFrame]:
    flights = pd.read_csv(os.path.join(data_dir, "mock_flights_by_date.csv"))
    hotels  = pd.read_csv(os.path.join(data_dir, "mock_hotels.csv"))
    return flights, hotels

def available_destinations(hotels_df: pd.DataFrame) -> list[str]:
    for col in ["city", "destination", "location"]:
        if col in hotels_df.columns:
            return sorted(list(map(str, hotels_df[col].dropna().unique())))
    return []

def _col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _to_float(v) -> Optional[float]:
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v)
    except Exception:
        return None


def find_options(
    flights_df: pd.DataFrame,
    hotels_df: pd.DataFrame,
    origin: str,
    destination: str,
    start_date: str,
    days: int,
    budget: float,
    max_pairs: int = 50000,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[float]]:
    """
    Return (best_flight_roundtrip, best_hotel, total_price_usd) where the combination
    has the **maximum total spend <= budget**.

    Assumptions:
      - 1 adult traveler
      - nights = max(1, days - 1)
      - return on start_date + (days - 1)

    Tie-breakers (when totals are equal):
      1) Higher hotel rating if available (rating_out_of_10, else star_rating/stars)
      2) Higher roundtrip flight spend (uses more budget)
      3) Arbitrary stable order
    """

    f_origin = _col(flights_df, ["departure_city", "origin", "from", "depart_city"])
    f_dest   = _col(flights_df, ["arrival_city", "destination", "to", "arrive_city"])
    f_date   = _col(flights_df, ["departure_date", "date", "flight_date", "depart_date"])
    f_price  = _col(flights_df, ["price_per_adult_usd", "price_usd", "price", "price_per_ticket_usd", "fare_usd"])
    f_dir    = _col(flights_df, ["direction"])

    h_city   = _col(hotels_df, ["city", "destination", "location"])
    h_price  = _col(hotels_df, ["price_per_night_usd", "price_usd", "nightly_usd", "price_per_night"])
    h_av_s   = _col(hotels_df, ["availability_start_date"])
    h_av_e   = _col(hotels_df, ["availability_end_date"])
    h_rating = _col(hotels_df, ["rating_out_of_10", "star_rating", "stars"])

    if not all([f_origin, f_dest, f_date, f_price, h_city, h_price]):
        return None, None, None

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except Exception:
        return None, None, None

    nights = max(1, int(days) - 1)
    return_date = start + timedelta(days=int(days) - 1)

    out_mask = (
        (flights_df[f_origin].astype(str).str.lower() == str(origin).lower()) &
        (flights_df[f_dest].astype(str).str.lower()   == str(destination).lower()) &
        (pd.to_datetime(flights_df[f_date], errors="coerce").dt.date == start)
    )
    if f_dir:
        out_mask &= flights_df[f_dir].astype(str).str.upper().eq("OUTBOUND")
    out = flights_df[out_mask].copy()

    ret_mask = (
        (flights_df[f_origin].astype(str).str.lower() == str(destination).lower()) &
        (flights_df[f_dest].astype(str).str.lower()   == str(origin).lower()) &
        (pd.to_datetime(flights_df[f_date], errors="coerce").dt.date == return_date)
    )
    if f_dir:
        ret_mask &= flights_df[f_dir].astype(str).str.upper().eq("RETURN")
    ret = flights_df[ret_mask].copy()

    if out.empty or ret.empty:
        return None, None, None

    out["_price"] = out[f_price].apply(_to_float)
    ret["_price"] = ret[f_price].apply(_to_float)
    out = out.dropna(subset=["_price"])
    ret = ret.dropna(subset=["_price"])
    if out.empty or ret.empty:
        return None, None, None

    roundtrips: List[Dict[str, Any]] = []
    count = 0
    for _, o in out.iterrows():
        o_price = float(o["_price"])
        for _, r in ret.iterrows():
            r_price = float(r["_price"])
            roundtrips.append({
                "outbound": o.to_dict(),
                "return":   r.to_dict(),
                "roundtrip_price_usd": o_price + r_price
            })
            count += 1
            if count >= max_pairs:
                break
        if count >= max_pairs:
            break
    if not roundtrips:
        return None, None, None

    roundtrips.sort(key=lambda x: x["roundtrip_price_usd"])
    rt_prices = [float(rt["roundtrip_price_usd"]) for rt in roundtrips]

    hmask = hotels_df[h_city].astype(str).str.lower().eq(str(destination).lower())
    if h_av_s and h_av_e:
        av_s = pd.to_datetime(hotels_df[h_av_s], errors="coerce").dt.date
        av_e = pd.to_datetime(hotels_df[h_av_e], errors="coerce").dt.date
        hmask &= (av_s <= start) & (av_e >= return_date)

    hotels = hotels_df[hmask].copy()
    if hotels.empty:
        return None, None, None

    hotels["_nightly"] = hotels[h_price].apply(_to_float)
    hotels = hotels.dropna(subset=["_nightly"])
    if hotels.empty:
        return None, None, None

    hotels["_total_hotel"] = hotels["_nightly"] * nights
    if h_rating:
        hotels["_rating"] = hotels[h_rating].apply(_to_float)
    else:
        hotels["_rating"] = None

    hotels_sorted = hotels.sort_values(by="_total_hotel", ascending=False)

    best_total = -1.0
    best_f: Optional[Dict[str, Any]] = None
    best_h: Optional[Dict[str, Any]] = None

    for _, h in hotels_sorted.iterrows():
        hotel_total = float(h["_total_hotel"])
        remain = float(budget) - hotel_total
        if remain < 0:
            continue  

        idx = bisect.bisect_right(rt_prices, remain) - 1
        if idx < 0:
            continue  

        rt = roundtrips[idx]
        flight_total = float(rt["roundtrip_price_usd"])
        total = flight_total + hotel_total

        if total > best_total and total <= float(budget):
            best_total = total
            best_f = {
                "outbound": rt["outbound"],
                "return": rt["return"],
                "roundtrip_price_usd": flight_total,
            }
            best_h = h.to_dict()
        elif abs(total - best_total) < 1e-6 and best_h is not None and best_f is not None:
            curr_rating = h.get("_rating", None)
            prev_rating = best_h.get("_rating", None)
            improved = False
            if (curr_rating is not None) and (prev_rating is not None) and (curr_rating > prev_rating):
                improved = True
            elif (curr_rating is not None) and (prev_rating is None):
                improved = True
            elif flight_total > float(best_f["roundtrip_price_usd"]):
                improved = True
            if improved:
                best_total = total
                best_f = {
                    "outbound": rt["outbound"],
                    "return": rt["return"],
                    "roundtrip_price_usd": flight_total,
                }
                best_h = h.to_dict()

    if best_f is None or best_h is None or best_total < 0:
        return None, None, None

    best_h.pop("_nightly", None)
    best_h.pop("_total_hotel", None)
    best_h.pop("_rating", None)

    return best_f, best_h, float(best_total)
