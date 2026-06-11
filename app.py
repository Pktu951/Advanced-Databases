"""
app.py — dashboard Streamlit dla kursów walut NBP.

Uruchomienie:
    streamlit run app.py

Filtry:
    1. zakres dat
    2. waluta (wiele naraz)
    3. typ tabeli (A / B / C)
    4. zakres wartości kursu
    5. okres agregacji (dzień / tydzień / miesiąc)
    6. ★ waluta bazowa (PLN lub dowolna z wybranych — kurs krzyżowy)

Zmiany względem v1:
  - zapytania filtrują też po table_type w exchange_rates
  - tabela C poprawnie ładuje bid/ask
  - kurs krzyżowy: dzielenie szeregów walutowych przez kurs waluty bazowej
"""

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text

from db import engine

st.set_page_config(page_title="Kursy walut NBP", layout="wide")
st.title("Kursy walut NBP — monitoring i wizualizacja")


# --- Pomocnicze -----------------------------------------------------------

@st.cache_data(ttl=600)
def get_currencies(table_type: str) -> pd.DataFrame:
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
def load_rates(codes: tuple, table_type: str, start, end, agg: str) -> pd.DataFrame:
    """Pobiera kursy z bazy z agregacją po wybranym okresie.

    Dla A/B używamy 'mid', dla C bierzemy 'bid' jako wartość referencyjną.
    Filtrujemy po table_type w exchange_rates (POPRAWKA).
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
          AND table_type = :tt
          AND rate_date BETWEEN :start AND :end
          AND {value_col} IS NOT NULL
        GROUP BY okres, currency_code
        ORDER BY okres
    """)
    return pd.read_sql(
        q, engine,
        params={"trunc": trunc, "codes": list(codes), "tt": table_type,
                "start": start, "end": end},
    )


def compute_cross_rates(df: pd.DataFrame, base_currency: str) -> pd.DataFrame:
    """Przelicza kursy na wybraną walutę bazową (zamiast PLN).

    Kurs krzyżowy: cena_A_w_PLN / cena_BASE_w_PLN = cena_A_w_BASE

    Przykład: USD/PLN = 4.0, EUR/PLN = 4.4 → EUR/USD = 4.4 / 4.0 = 1.10

    Jeśli baza to PLN — zwraca dane bez zmian.
    """
    if base_currency == "PLN":
        return df

    # Dodajemy PLN jako wirtualną walutę z kursem 1.0 — po przeliczeniu
    # pokaże ile jednostek waluty bazowej kosztuje 1 złotówka (np. PLN/EUR).
    periods = df["okres"].unique()
    pln_rows = pd.DataFrame({
        "okres": periods,
        "currency_code": "PLN",
        "wartosc": 1.0,
    })
    df = pd.concat([df, pln_rows], ignore_index=True)

    base_df = df[df["currency_code"] == base_currency][["okres", "wartosc"]].copy()
    base_df = base_df.rename(columns={"wartosc": "base_wartosc"})

    result = df.merge(base_df, on="okres", how="inner")
    result["wartosc"] = result["wartosc"] / result["base_wartosc"]
    result = result.drop(columns=["base_wartosc"])
    # walutę bazową usuwamy z wykresu — jej kurs do siebie samej to zawsze 1.0
    result = result[result["currency_code"] != base_currency]
    return result


# --- Sidebar: filtry -------------------------------------------------------

st.sidebar.header("Filtry")

# Filtr 3 — typ tabeli (determinuje listę walut)
table_type = st.sidebar.radio(
    "Typ tabeli", ["A", "B", "C"],
    help="A/B — kurs średni (mid). C — kurs kupna (bid).",
)

curr_df = get_currencies(table_type)
code_options = curr_df["code"].tolist()

# Filtr 2 — waluta (wielokrotny wybór)
default_codes = [c for c in ["USD", "EUR", "GBP"] if c in code_options]
codes = st.sidebar.multiselect(
    "Waluty", code_options,
    default=default_codes or code_options[:3],
)

# Filtr 1 — zakres dat
dmin, dmax = get_date_bounds()
date_range = st.sidebar.date_input(
    "Zakres dat", value=(max(dmin, dmax - dt.timedelta(days=365)), dmax),
    min_value=dmin, max_value=dmax,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
else:
    start, end = dmin, dmax

# Filtr 5 — okres agregacji
agg = st.sidebar.selectbox("Agregacja", ["dzień", "tydzień", "miesiąc"], index=0)

# Filtr 6 ★ — waluta bazowa (kurs krzyżowy)
base_options = ["PLN"] + (codes if codes else [])
base_currency = st.sidebar.selectbox(
    "Waluta bazowa",
    base_options,
    index=0,
    help=(
        "PLN — klasyczny kurs do złotego.\n"
        "Inna waluta — kurs krzyżowy: ile jednostek tej waluty kosztuje 1 jednostka "
        "wybranej waluty. Np. EUR przy bazie USD = EUR/USD."
    ),
)

# --- Pobranie danych -------------------------------------------------------

if not codes:
    st.warning("Wybierz przynajmniej jedną walutę w panelu po lewej.")
    st.stop()

# multiselect zwraca listę; cache_data wymaga hashable → tuple
df = load_rates(tuple(sorted(codes)), table_type, start, end, agg)

if df.empty:
    st.warning("Brak danych dla wybranych filtrów. "
               "Upewnij się, że ETL załadował dane dla tabeli " + table_type + ".")
    st.stop()

# Kurs krzyżowy
df = compute_cross_rates(df, base_currency)

if df.empty:
    st.warning(f"Brak wspólnych dat dla waluty bazowej ({base_currency}) "
               "i wybranych walut. Spróbuj zmienić zakres dat lub walutę bazową.")
    st.stop()

# Etykieta osi Y
y_label = f"Kurs ({base_currency})" if base_currency != "PLN" else "Kurs (PLN)"

# Filtr 4 — suwak wartości (po przeliczeniu, żeby zakres odpowiadał wykresowi)
vmin = float(df["wartosc"].min())
vmax = float(df["wartosc"].max())
if vmin < vmax:
    val_range = st.sidebar.slider(
        f"Zakres wartości kursu ({base_currency})",
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
    st.subheader(
        f"Kurs w czasie"
        + (f" — baza: {base_currency}" if base_currency != "PLN" else " — baza: PLN")
    )

    # Tabela C: opcjonalnie pokaż bid i ask osobno
    if table_type == "C" and base_currency == "PLN":
        show_spread = st.checkbox("Pokaż spread (bid/ask) dla tabeli C", value=False)
    else:
        show_spread = False

    if show_spread and table_type == "C":
        # Pobierz bid i ask osobno do spreadu
        @st.cache_data(ttl=600)
        def load_bid_ask(codes_t, table_type_t, start_t, end_t, agg_t):
            trunc = {"dzień": "day", "tydzień": "week", "miesiąc": "month"}[agg_t]
            q = text(f"""
                SELECT
                    date_trunc(:trunc, rate_date)::date AS okres,
                    currency_code,
                    AVG(bid) AS bid,
                    AVG(ask) AS ask
                FROM exchange_rates
                WHERE currency_code = ANY(:codes)
                  AND table_type = :tt
                  AND rate_date BETWEEN :start AND :end
                  AND bid IS NOT NULL AND ask IS NOT NULL
                GROUP BY okres, currency_code
                ORDER BY okres
            """)
            return pd.read_sql(
                q, engine,
                params={"trunc": trunc, "codes": list(codes_t),
                        "tt": table_type_t, "start": start_t, "end": end_t},
            )

        df_ba = load_bid_ask(tuple(sorted(codes)), table_type, start, end, agg)
        if not df_ba.empty:
            # Dla jednej waluty rysujemy spread jako ribbon
            chosen = st.selectbox("Waluta do spreadu", codes)
            df_c = df_ba[df_ba["currency_code"] == chosen]
            fig = px.line(df_c, x="okres", y=["bid", "ask"],
                          labels={"okres": "Data", "value": "Kurs (PLN)",
                                  "variable": "Typ"},
                          title=f"Spread bid/ask — {chosen}")
            fig.update_layout(hovermode="x unified", height=450)
            st.plotly_chart(fig, use_container_width=True)
    else:
        fig = px.line(
            df, x="okres", y="wartosc", color="currency_code",
            labels={"okres": "Data", "wartosc": y_label,
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
    stats["zmiennosc_%"] = (
        (stats["max"] - stats["min"]) / stats["srednia"] * 100
    ).round(2)
    st.dataframe(stats, use_container_width=True)

    st.subheader("Rozkład kursu")
    fig2 = px.histogram(
        df, x="wartosc", color="currency_code", barmode="overlay",
        nbins=40,
        labels={"wartosc": y_label, "currency_code": "Waluta"},
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)

st.caption(
    f"Źródło: API NBP · {len(df)} punktów danych · "
    f"tabela {table_type} · baza: {base_currency} · {start} — {end}"
)
