# Kursy walut NBP

Dashboard do monitorowania i wizualizacji kursów walut z API Narodowego Banku Polskiego.

## Wymagania

- Python 3.11+
- PostgreSQL 14+

Zainstaluj zależności:
```bash
pip install streamlit sqlalchemy psycopg2-binary pandas plotly requests
```

## Konfiguracja bazy danych

Utwórz bazę i użytkownika w PostgreSQL:
```sql
CREATE DATABASE "NBP";
CREATE USER nbp_user WITH PASSWORD 'nbp123';
GRANT ALL PRIVILEGES ON DATABASE "NBP" TO nbp_user;
```

Jeśli chcesz inne dane logowania, zmień je bezpośrednio w `db.py`:
```python
DB_USER = "nbp_user"
DB_PASS  = "nbp123"
DB_HOST  = "localhost"
DB_PORT  = 5432
DB_NAME  = "NBP"
```

## Pierwsze uruchomienie

Utwórz schemat i pobierz wszystkie dane historyczne (od 2002):
```bash
python etl.py --full
```

Trwa kilkanaście minut. Jeśli chcesz tylko konkretny zakres lat (np. do testów):
```bash
python etl.py 2023 2025
```

## Codzienne aktualizacje

Bez argumentów ETL sprawdza ostatni dzień w bazie i pobiera tylko brakujące dane:
```bash
python etl.py
```

Można zautomatyzować cronem:
```
0 8 * * * cd /ścieżka/do/projektu && python etl.py >> etl.log 2>&1
```

## Uruchomienie dashboardu

```bash
streamlit run app.py
```

Dashboard dostępny pod `http://localhost:8501`.

## Struktura projektu

```
.
├── app.py      # dashboard Streamlit
├── db.py       # schemat bazy i silnik SQLAlchemy
├── etl.py      # pobieranie danych z API NBP
└── README.md
```

## Funkcje dashboardu

- **Szereg czasowy** — wykres liniowy kursów wybranych walut
- **Analiza ilościowa** — statystyki opisowe + histogram rozkładu
- **Filtry:** zakres dat, wybór walut, typ tabeli (A/B/C), agregacja czasowa, zakres wartości
- **Kurs krzyżowy** — zmiana waluty bazowej z PLN na dowolną wybraną walutę
- **Spread bid/ask** — dla tabeli C podgląd obu kursów jednocześnie

## Tabele NBP

| Tabela | Zawiera | Kolumna w bazie |
|--------|---------|-----------------|
| A | Kursy średnie walut wymienialnych | `mid` |
| B | Kursy średnie walut egzotycznych | `mid` |
| C | Kursy kupna i sprzedaży | `bid` / `ask` |
