"""Portfolio tool: holdings and value from RDS Postgres."""

import psycopg

DSN = "postgresql://app@portfolio-db/portfolio"

QUERY = """
SELECT h.symbol, h.qty, p.last_price, h.qty * p.last_price AS value
FROM holdings h JOIN prices p ON p.symbol = h.symbol
WHERE h.user_id = %s
"""


def fetch(user, timeout):
    with psycopg.connect(DSN, connect_timeout=timeout) as conn:
        conn.execute(f"SET statement_timeout = {int(timeout * 1000)}")
        rows = conn.execute(QUERY, (user,)).fetchall()
    return {"holdings": rows, "value": sum(r[3] for r in rows)}
