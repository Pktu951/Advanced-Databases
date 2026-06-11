"""
etl.py — pobiera dane z API NBP i ładuje do bazy.

Uruchomienie:
    python etl.py              # inkrementalnie: tylko brakujące dni
    python etl.py --full       # pełny backfill od 2002 do dziś
    python etl.py 2024 2026    # backfill tylko podanego zakresu lat

Idempotentny: duplikaty są pomijane dzięki on_conflict_do_nothing.
"""

import sys
import time
import datetime as dt

import requests
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from db import engine, currencies, exchange_rates, init_db

API = "https://api.nbp.pl/api"
TABLES = ["A", "B", "C"]
START_YEAR = 2002
TIMEOUT = 30
SLEEP = 0.2


# --- Pomocnicze -----------------------------------------------------------

def get_json(url: str):
    """GET z obsługą 404 (brak danych w okresie) — zwraca None."""
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def daterange_chunks(start: dt.date, end: dt.date, max_days: int = 90):
    """Generuje (start, end) po max ~90 dni — limit API NBP to 93 dni."""
    current = start
    while current <= end:
        chunk_end = min(current + dt.timedelta(days=max_days - 1), end)
        yield current, chunk_end
        current = chunk_end + dt.timedelta(days=1)


def get_last_loaded_date(table_type: str) -> dt.date | None:
    """Zwraca ostatni załadowany dzień dla danego typu tabeli.

    Dzięki temu ETL wie od kiedy pobierać nowe dane — nie musi
    przechodzić przez wszystkie lata od 2002.
    """
    q = text("""
        SELECT MAX(rate_date)
        FROM exchange_rates
        WHERE table_type = :tt
    """)
    with engine.connect() as conn:
        result = conn.execute(q, {"tt": table_type}).scalar()
    return result  # None jeśli tabela pusta


# --- Etap 1: currencies ---------------------------------------------------

def load_currencies():
    """Pobiera aktualną listę walut z tabel A/B/C."""
    rows = []
    seen: set[tuple[str, str]] = set()

    for table in TABLES:
        data = get_json(f"{API}/exchangerates/tables/{table}/?format=json")
        time.sleep(SLEEP)
        if not data:
            continue
        for rate in data[0]["rates"]:
            code = rate["code"]
            key = (code, table)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "code": code,
                "name": rate["currency"],
                "table_type": table,
            })

    with engine.begin() as conn:
        stmt = insert(currencies).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["code", "table_type"])
        conn.execute(stmt)
    print(f"currencies: {len(rows)} walut (A+B+C).")


# --- Etap 2: kursy --------------------------------------------------------

def parse_day(table: str, day: dict) -> list[dict]:
    out = []
    table_no = day["no"]
    rate_date = day["effectiveDate"]
    for rate in day["rates"]:
        row = {
            "currency_code": rate["code"],
            "table_type": table,
            "rate_date": rate_date,
            "table_no": table_no,
            "mid": None,
            "bid": None,
            "ask": None,
        }
        if table in ("A", "B"):
            row["mid"] = rate["mid"]
        else:
            row["bid"] = rate["bid"]
            row["ask"] = rate["ask"]
        out.append(row)
    return out


def insert_rows(rows: list[dict], batch_size: int = 500):
    seen: set[tuple] = set()
    unique = []
    for r in rows:
        key = (r["currency_code"], r["table_type"], r["rate_date"], r["table_no"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    def one_insert(conn, batch):
        stmt = insert(exchange_rates).values(batch)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["currency_code", "table_type", "rate_date", "table_no"]
        )
        conn.execute(stmt)

    for i in range(0, len(unique), batch_size):
        batch = unique[i:i + batch_size]
        try:
            with engine.begin() as conn:
                one_insert(conn, batch)
        except Exception:
            for r in batch:
                try:
                    with engine.begin() as conn:
                        one_insert(conn, [r])
                except Exception:
                    pass


def load_rates(start: dt.date, end: dt.date, label: str = ""):
    """Pobiera kursy dla wszystkich tabel w podanym zakresie dat."""
    today = dt.date.today()
    end = min(end, today)
    if start > end:
        print(f"  {label}Baza aktualna, nic do pobrania.")
        return

    total = 0
    for table in TABLES:
        for chunk_start, chunk_end in daterange_chunks(start, end):
            url = (f"{API}/exchangerates/tables/{table}/"
                   f"{chunk_start.isoformat()}/{chunk_end.isoformat()}/?format=json")
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
            print(f"  [{table}] {chunk_start}–{chunk_end}: +{len(rows)} wierszy")

    print(f"{label}Razem: {total} nowych wierszy.")


# --- Main -----------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    print("0) Tworzę schemat (jeśli trzeba)...")
    init_db()

    print("1) Ładuję currencies...")
    load_currencies()

    if len(args) == 2 and args[0] != "--full":
        # tryb: python etl.py 2024 2026
        start_date = dt.date(int(args[0]), 1, 1)
        end_date = dt.date(int(args[1]), 12, 31)
        print(f"2) Backfill {start_date}–{end_date}...")
        load_rates(start_date, end_date, label="Backfill: ")

    elif "--full" in args:
        # tryb: python etl.py --full
        start_date = dt.date(START_YEAR, 1, 1)
        end_date = dt.date.today()
        print(f"2) Pełny backfill {start_date}–{end_date}...")
        load_rates(start_date, end_date, label="Pełny backfill: ")

    else:
        # tryb domyślny: inkrementalny — pobierz tylko brakujące dni
        print("2) Aktualizacja inkrementalna...")
        for table in TABLES:
            last = get_last_loaded_date(table)
            if last is None:
                # tabela pusta — pełny backfill dla tej tabeli
                start_date = dt.date(START_YEAR, 1, 1)
                print(f"  [{table}] Brak danych — backfill od {start_date}...")
            else:
                # zacznij od następnego dnia po ostatnim załadowanym
                start_date = last + dt.timedelta(days=1)
                print(f"  [{table}] Ostatni dzień w bazie: {last}, "
                      f"pobieram od {start_date}...")
            load_rates(start_date, dt.date.today(), label=f"[{table}] ")

    print("Gotowe.")
