"""
app.py — dashboard Streamlit dla kursów walut NBP.

Uruchomienie:
    streamlit run app.py

Dwie kategorie wizualizacji (szereg czasowy + analiza ilościowa),
każda reagująca na te same 5 filtrów:
    1. zakres dat
    2. waluta (wiele naraz)
    3. typ tabeli (A / B / C)
    4. zakres wartości kursu
    5. okres agregacji (dzień / tydzień / miesiąc)
"""

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text

from db import engine

st.set_page_config(page_title="Kursy walut NBP", layout="wide")
st.title("Kursy walut NBP — monitoring i wizualizacja")


# --- Pomocnicze (cache, żeby nie odpytywać bazy w kółko) ------------------

@st.cache_data(ttl=600)
def get_currencies(table_type):
    """Lista walut dostępnych dla danego typu tabeli."""
    q = text("""
        SELECT DISTINCT c.code, c.name
        FROM currencies c
        WHERE c.table_type = :tt
        ORDER BY c.code
    """)
    return pd.read_sql(q, engine, params={"tt": table_type})


@st.cache_data(ttl=600)
def get_date_bounds():
    q = text("SELECT MIN(rate_date) AS mn, MAX(rate_date) AS mx "
             "FROM exchange_rates")
    df = pd.read_sql(q, engine)
    return df["mn"].iloc[0], df["mx"].iloc[0]


@st.cache_data(ttl=600)
def load_rates(codes, table_type, start, end, agg):
    """Pobiera kursy z bazy z agregacją po wybranym okresie.

    Dla A/B używamy 'mid', dla C bierzemy 'bid' jako wartość referencyjną.
    """
    value_col = "mid" if table_type in ("A", "B") else "bid"

    trunc = {"dzień": "day", "tydzień": "week", "miesiąc": "month"}[agg]

    q = text(f"""
        SELECT
            date_trunc(:trunc, rate_date)::date AS okres,
            currency_code,
            AVG({value_col}) AS wartosc
        FROM exchange_rates
        WHERE currency_code = ANY(:codes)
          AND rate_date BETWEEN :start AND :end
          AND {value_col} IS NOT NULL
        GROUP BY okres, currency_code
        ORDER BY okres
    """)
    return pd.read_sql(
        q, engine,
        params={"trunc": trunc, "codes": codes, "start": start, "end": end},
    )


# --- Sidebar: 5 FILTRÓW ---------------------------------------------------

st.sidebar.header("Filtry")

# Filtr 3 (typ tabeli) — pierwszy, bo determinuje listę walut
table_type = st.sidebar.radio(
    "Typ tabeli", ["A", "B", "C"],
    help="A/B — kurs średni (mid). C — kurs kupna/sprzedaży (bid/ask).",
)

curr_df = get_currencies(table_type)
code_options = curr_df["code"].tolist()

# Filtr 2 (waluta, wielokrotny wybór)
default_codes = [c for c in ["USD", "EUR", "GBP"] if c in code_options]
codes = st.sidebar.multiselect(
    "Waluty", code_options,
    default=default_codes or code_options[:3],
)

# Filtr 1 (zakres dat)
dmin, dmax = get_date_bounds()
date_range = st.sidebar.date_input(
    "Zakres dat", value=(max(dmin, dmax - dt.timedelta(days=365)), dmax),
    min_value=dmin, max_value=dmax,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
else:
    start, end = dmin, dmax

# Filtr 5 (okres agregacji)
agg = st.sidebar.selectbox("Agregacja", ["dzień", "tydzień", "miesiąc"], index=0)

# --- Pobranie danych ------------------------------------------------------

if not codes:
    st.warning("Wybierz przynajmniej jedną walutę w panelu po lewej.")
    st.stop()

df = load_rates(codes, table_type, start, end, agg)

if df.empty:
    st.warning("Brak danych dla wybranych filtrów.")
    st.stop()

# Filtr 4 (zakres wartości kursu) — suwak na podstawie danych
vmin = float(df["wartosc"].min())
vmax = float(df["wartosc"].max())
if vmin < vmax:
    val_range = st.sidebar.slider(
        "Zakres wartości kursu (PLN)",
        min_value=round(vmin, 4), max_value=round(vmax, 4),
        value=(round(vmin, 4), round(vmax, 4)),
    )
    df = df[(df["wartosc"] >= val_range[0]) & (df["wartosc"] <= val_range[1])]

if df.empty:
    st.warning("Brak danych po zastosowaniu filtra wartości.")
    st.stop()


# --- Wizualizacje: dwie zakładki ------------------------------------------

tab1, tab2 = st.tabs(["Szereg czasowy", "Analiza ilościowa"])

with tab1:
    st.subheader("Kurs w czasie")
    fig = px.line(
        df, x="okres", y="wartosc", color="currency_code",
        labels={"okres": "Data", "wartosc": "Kurs (PLN)",
                "currency_code": "Waluta"},
    )
    fig.update_layout(hovermode="x unified", height=500)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Statystyki opisowe")
    stats = (
        df.groupby("currency_code")["wartosc"]
        .agg(min="min", max="max", srednia="mean",
             mediana="median", odchylenie="std")
        .round(4)
    )
    # zmienność procentowa (rozstęp / średnia)
    stats["zmiennosc_%"] = (
        (stats["max"] - stats["min"]) / stats["srednia"] * 100
    ).round(2)
    st.dataframe(stats, use_container_width=True)

    st.subheader("Rozkład kursu")
    fig2 = px.histogram(
        df, x="wartosc", color="currency_code", barmode="overlay",
        nbins=40,
        labels={"wartosc": "Kurs (PLN)", "currency_code": "Waluta"},
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)

st.caption(f"Źródło: API NBP · {len(df)} punktów danych · "
           f"tabela {table_type} · {start} — {end}")