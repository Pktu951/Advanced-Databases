"""
db.py - definicja schematu bazy NBP i silnika SQLAlchemy.
"""

from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Integer, BigInteger, Date, Numeric, Text,
    ForeignKey, UniqueConstraint, Index,
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
    Column("code", String(3), primary_key=True),
    Column("name", Text, nullable=False),
    Column("table_type", String(1), nullable=False),
)

exchange_rates = Table(
    "exchange_rates", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("currency_code", String(3),
           ForeignKey("currencies.code"), nullable=False),
    Column("rate_date", Date, nullable=False),
    Column("mid", Numeric(12, 6)),
    Column("bid", Numeric(12, 6)),
    Column("ask", Numeric(12, 6)),
    Column("table_no", Text),
    UniqueConstraint("currency_code", "rate_date", "table_no",
                     name="uq_rate"),
    Index("idx_rates_date", "rate_date"),
    Index("idx_rates_curr", "currency_code"),
)


def init_db():
    metadata.create_all(engine)
    print("Schemat utworzony (lub juz istnial).")


if __name__ == "__main__":
    init_db()