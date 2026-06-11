"""
db.py - definicja schematu bazy NBP i silnika SQLAlchemy.

Schemat:
  - currencies: PK złożony (code, table_type) — ta sama waluta może być
    w tabeli A i C jednocześnie (mid vs bid/ask).
  - exchange_rates: przechowuje table_type jawnie, FK na (currency_code, table_type).

Indeksy w exchange_rates:
  - (table_type, rate_date) — główny filtr dashboardu: zakres dat w obrębie tabeli
  - (currency_code)         — pomocniczy, przy filtrowaniu po pojedynczej walucie
  Nie używamy indeksu złożonego z currency_code w środku, bo zapytania filtrują
  po currency_code = ANY(:lista), co uniemożliwia efektywne użycie indeksu złożonego.
"""

from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, BigInteger, Date, Numeric, Text,
    ForeignKeyConstraint, UniqueConstraint, Index,
)

DB_USER = "nbp_user"
DB_PASS = "nbp123"
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "NBP"

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL, future=True)
metadata = MetaData()

currencies = Table(
    "currencies", metadata,
    Column("code", String(3), nullable=False),
    Column("name", Text, nullable=False),
    Column("table_type", String(1), nullable=False),
    UniqueConstraint("code", "table_type", name="pk_currencies"),
)

exchange_rates = Table(
    "exchange_rates", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("currency_code", String(3), nullable=False),
    Column("table_type", String(1), nullable=False),
    Column("rate_date", Date, nullable=False),
    Column("mid", Numeric(12, 6)),
    Column("bid", Numeric(12, 6)),
    Column("ask", Numeric(12, 6)),
    Column("table_no", Text),
    ForeignKeyConstraint(
        ["currency_code", "table_type"],
        ["currencies.code", "currencies.table_type"],
        name="fk_rates_currency",
    ),
    UniqueConstraint(
        "currency_code", "table_type", "rate_date", "table_no",
        name="uq_rate",
    ),
    Index("idx_rates_table_date", "table_type", "rate_date"),
    Index("idx_rates_curr", "currency_code"),
)


def init_db():
    metadata.create_all(engine)
    print("Schemat utworzony (lub już istniał).")


if __name__ == "__main__":
    init_db()
