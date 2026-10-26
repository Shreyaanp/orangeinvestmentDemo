CREATE TABLE holdings (
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

CREATE TABLE prices (
    symbol TEXT PRIMARY KEY,
    last_price NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
