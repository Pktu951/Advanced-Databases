"""
etl.py — pobiera dane z API NBP i ładuje do bazy.

Uruchomienie:
    python etl.py              # currencies + backfill 2002..bieżący rok
    python etl.py 2024 2026    # currencies + backfill tylko 2024..2026

Idempotentny: można puszczać wielokrotnie, duplikaty są pomijane
dzięki on_conflict_do_nothing.
"""

import sys
import time
import datetime as dt

import requests
from sqlalchemy.dialects.postgresql import insert

from db import engine, currencies, exchange_rates, init_db

API = "https://api.nbp.pl/api"
TABLES = ["A", "B", "C"]
START_YEAR = 2002
TIMEOUT = 30
SLEEP = 0.2  # przerwa między requestami, żeby nie dostać throttlingu


# --- Pomocnicze -----------------------------------------------------------

def get_json(url):
    """GET z obsługą 404 (brak danych w okresie) — zwraca None."""
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def daterange_chunks(start_year, end_year, max_days=90):
    """Generuje (start, end) po max ~90 dni — limit API NBP to 93 dni."""
    today = dt.date.today()
    current = dt.date(start_year, 1, 1)
    last = min(dt.date(end_year, 12, 31), today)
    while current <= last:
        chunk_end = min(current + dt.timedelta(days=max_days - 1), last)
        yield current.year, current.isoformat(), chunk_end.isoformat()
        current = chunk_end + dt.timedelta(days=1)


# --- Etap 1: currencies ---------------------------------------------------

def load_currencies():
    """Pobiera aktualną listę walut z tabel A/B/C i wypełnia currencies."""
    rows = []
    seen = set()
    for table in TABLES:
        data = get_json(f"{API}/exchangerates/tables/{table}/?format=json")
        time.sleep(SLEEP)
        if not data:
            continue
        for rate in data[0]["rates"]:
            code = rate["code"]
            if code in seen:
                continue
            seen.add(code)
            rows.append({
                "code": code,
                "name": rate["currency"],
                "table_type": table,
            })

    with engine.begin() as conn:
        stmt = insert(currencies).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
        conn.execute(stmt)
    print(f"currencies: załadowano {len(rows)} walut.")


# --- Etap 2: backfill kursów ---------------------------------------------

def parse_day(table, day):
    """Zamienia jeden dzień odpowiedzi API na listę dictów do insertu."""
    out = []
    table_no = day["no"]
    rate_date = day["effectiveDate"]
    for rate in day["rates"]:
        row = {
            "currency_code": rate["code"],
            "rate_date": rate_date,
            "table_no": table_no,
            "mid": None, "bid": None, "ask": None,
        }
        if table in ("A", "B"):
            row["mid"] = rate["mid"]
        else:  # tabela C ma bid/ask
            row["bid"] = rate["bid"]
            row["ask"] = rate["ask"]
        out.append(row)
    return out


def insert_rows(rows, batch_size=500):
    """Wstawia wiersze odpornie: odsiewa duplikaty, małe batche,
    a w razie błędu batcha — wstawia pojedynczo."""
    # 1) odsiej duplikaty klucza w obrębie tej porcji
    seen = set()
    unique = []
    for r in rows:
        key = (r["currency_code"], r["rate_date"], r["table_no"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    def one_insert(conn, batch):
        stmt = insert(exchange_rates).values(batch)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["currency_code", "rate_date", "table_no"]
        )
        conn.execute(stmt)

    for i in range(0, len(unique), batch_size):
        batch = unique[i:i + batch_size]
        try:
            with engine.begin() as conn:
                one_insert(conn, batch)
        except Exception:
            # batch się wywalił — wstaw wiersz po wierszu, pomijając problematyczne
            for r in batch:
                try:
                    with engine.begin() as conn:
                        one_insert(conn, [r])
                except Exception:
                    pass  # pojedynczy problematyczny wiersz pomijamy

def load_rates(start_year, end_year):
    total = 0
    for table in TABLES:
        for year, start, end in daterange_chunks(start_year, end_year):
            url = (f"{API}/exchangerates/tables/{table}/"
                   f"{start}/{end}/?format=json")
            data = get_json(url)
            time.sleep(SLEEP)
            if not data:
                continue

            rows = []
            for day in data:
                rows.extend(parse_day(table, day))

            if not rows:
                continue

            insert_rows(rows)

            total += len(rows)
            print(f"  [{table}] {year}: +{len(rows)} wierszy "
                  f"(łącznie {total})")
    print(f"exchange_rates: backfill zakończony, {total} wierszy.")

# --- Main -----------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) == 3:
        start_year, end_year = int(sys.argv[1]), int(sys.argv[2])
    else:
        start_year, end_year = START_YEAR, dt.date.today().year

    print("0) Tworzę schemat (jeśli trzeba)...")
    init_db()

    print("1) Ładuję currencies...")
    load_currencies()

    print(f"2) Backfill kursów {start_year}..{end_year}...")
    load_rates(start_year, end_year)

    print("Gotowe.")