-- F51/sql/001_signal_functions.sql
-- Signal Function Registry and Signal Log Tables
-- Task 1: 数据库建表

CREATE TABLE IF NOT EXISTS tb_signal_functions (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(64) NOT NULL UNIQUE,
    display_name  VARCHAR(128) NOT NULL,
    module_path   VARCHAR(256) NOT NULL,
    func_name     VARCHAR(64) NOT NULL,
    period        VARCHAR(16) NOT NULL,
    param_set_id  INTEGER DEFAULT 0,
    enabled       BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tb_signal_function_params (
    id            SERIAL PRIMARY KEY,
    func_id       INTEGER REFERENCES tb_signal_functions(id) ON DELETE CASCADE,
    set_id        INTEGER NOT NULL DEFAULT 0,
    param_key     VARCHAR(64) NOT NULL,
    param_value   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sfp_func_id ON tb_signal_function_params(func_id);

CREATE TABLE IF NOT EXISTS tb_signal_log (
    id            BIGSERIAL PRIMARY KEY,
    func_id       INTEGER REFERENCES tb_signal_functions(id) ON DELETE CASCADE,
    direction     VARCHAR(8) NOT NULL CHECK (direction IN ('buy', 'sell')),
    symbol        VARCHAR(32) NOT NULL,
    signal_time   TIMESTAMP NOT NULL,
    price         DOUBLE PRECISION,
    indicator     TEXT,
    pushed_at     TIMESTAMP DEFAULT NOW(),
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sl_func_time ON tb_signal_log(func_id, signal_time DESC);
CREATE INDEX IF NOT EXISTS idx_sl_symbol   ON tb_signal_log(symbol);
