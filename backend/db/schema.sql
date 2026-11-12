-- Dash FIDCs data model (version 1). PostgreSQL 16.
-- Conventions (same as Dash Fundos):
--   * Every fact row keeps where it came from: raw_file_id + competencia.
--   * Monthly snapshots are keyed by (cnpj, competencia); reloading a corrected zip replaces that month.
--   * Missing values are NULL, never estimated. Filer errors go to data_quality_issues.
--   * Money in NUMERIC(20,2); rates and shares as fractions (0.0962 = 9,62%).

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy search (Ctrl+K)

-- ---------------------------------------------------------------------------
-- Provenance and operations (shared with Dash Fundos' job framework)
-- ---------------------------------------------------------------------------
CREATE TABLE sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    label_pt        TEXT,
    base_url        TEXT,
    schedule        TEXT NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_data_date  DATE,
    last_error      TEXT,
    last_error_at   TIMESTAMPTZ,
    notes           TEXT
);

INSERT INTO sources (id, name, label_pt, base_url, schedule, notes) VALUES
 ('cvm_inf_mensal_fidc', 'CVM Informe Mensal FIDC', 'CVM – Informe Mensal FIDC',
  'https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/', 'daily',
  'Um zip por competência (inf_mensal_fidc_AAAAMM.zip); a CVM republica os meses recentes.'),
 ('cvm_cad_fidc', 'CVM Cadastro de fundos e classes (RCVM 175)', 'CVM – Cadastro de fundos e classes',
  'https://dados.cvm.gov.br/dados/FI/CAD/DADOS/', 'daily',
  'registro_fundo_classe.zip: gestor, administrador, custodiante, auditor, situação e PL do cadastro.');

CREATE TABLE raw_files (
    id          BIGSERIAL PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES sources(id),
    url         TEXT NOT NULL,
    sha256      CHAR(64) NOT NULL UNIQUE,
    bytes       BIGINT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_etag   TEXT,
    http_last_modified TEXT,
    content_type TEXT,
    sanitizer   TEXT
);
CREATE INDEX raw_files_url ON raw_files (url, fetched_at DESC);

CREATE TABLE raw_file_loads (
    raw_file_id BIGINT NOT NULL REFERENCES raw_files(id) ON DELETE CASCADE,
    loader      TEXT NOT NULL,
    rows        INTEGER,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (raw_file_id, loader)
);

CREATE TABLE job_runs (
    id           BIGSERIAL PRIMARY KEY,
    job_name     TEXT NOT NULL,
    trigger      TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',
    progress     NUMERIC(5,4),
    message      TEXT,
    log          TEXT,
    rows_changed INTEGER,
    params       JSONB,
    chain_id     TEXT
);
CREATE INDEX job_runs_name_started ON job_runs (job_name, started_at DESC);

CREATE TABLE data_quality_issues (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'warning',
    cnpj        CHAR(14),
    ref_month   DATE,
    document_id BIGINT,
    detail      JSONB NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- FIDCs
-- ---------------------------------------------------------------------------
-- One row per CNPJ that files the informe mensal (a fund before RCVM 175, a class after it).
CREATE TABLE fidcs (
    cnpj                CHAR(14) PRIMARY KEY,
    nome                TEXT NOT NULL,
    tipo                TEXT,                  -- 'Fundo' | 'Classe' (TP_FUNDO_CLASSE)
    cnpj_fundo          CHAR(14),              -- the fund a class belongs to (cadastro)
    nome_fundo          TEXT,
    situacao            TEXT,
    data_situacao       DATE,
    data_constituicao   DATE,
    data_registro       DATE,
    adaptacao_175       DATE,
    administrador       TEXT,
    cnpj_administrador  CHAR(14),
    gestor              TEXT,
    cnpj_gestor         TEXT,
    custodiante         TEXT,
    auditor             TEXT,
    condominio          TEXT,
    exclusivo           BOOLEAN,
    classe_unica        BOOLEAN,
    publico_alvo        TEXT,
    pl_cadastro         NUMERIC(20,2),
    data_pl_cadastro    DATE,
    ultima_competencia  DATE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX fidcs_nome_trgm ON fidcs USING gin (nome gin_trgm_ops);
CREATE INDEX fidcs_gestor ON fidcs (gestor);
CREATE INDEX fidcs_admin ON fidcs (administrador);

CREATE TABLE fidc_mensal (
    cnpj                CHAR(14) NOT NULL REFERENCES fidcs(cnpj) ON DELETE CASCADE,
    competencia         DATE NOT NULL,         -- first day of the month
    raw_file_id         BIGINT REFERENCES raw_files(id) ON DELETE SET NULL,
    pl                  NUMERIC(20,2),
    pl_medio            NUMERIC(20,2),
    ativo               NUMERIC(20,2),
    disponibilidades    NUMERIC(20,2),
    carteira            NUMERIC(20,2),
    dc_com_risco        NUMERIC(20,2),
    dc_sem_risco        NUMERIC(20,2),
    a_vencer            NUMERIC(20,2),         -- tab V + VI, item A
    inadimplente        NUMERIC(20,2),         -- tab V + VI, item B
    inad_acima_90       NUMERIC(20,2),         -- vencidos há mais de 90 dias
    antecipado          NUMERIC(20,2),
    inadimplencia       NUMERIC(10,6),         -- inadimplente / (a_vencer + inadimplente)
    pdd_sobre_dc        NUMERIC(10,6),         -- provisão (TAB_I2A11) / DC com risco
    segmentos           JSONB,                 -- {"Consignado": 123.4, ...} folhas da tabela II
    segmento            TEXT,                  -- maior segmento
    subsegmento         TEXT,
    peso_segmento       NUMERIC(10,6),
    subordinacao        NUMERIC(10,6),         -- (subordinada + mezanino) / valor total das cotas
    valor_cotas         NUMERIC(20,2),
    valor_senior        NUMERIC(20,2),
    valor_subordinada   NUMERIC(20,2),
    cotistas            INTEGER,
    cotistas_tipo       JSONB,                 -- {"Pessoa física": 10, ...}
    alocador_tipo       TEXT,                  -- tipo com mais da metade dos cotistas, ou 'Misto'
    rentab_senior       NUMERIC(12,8),         -- maior série sênior, no mês
    rentab_subordinada  NUMERIC(12,8),
    captacao            NUMERIC(20,2),
    resgate             NUMERIC(20,2),
    amortizacao         NUMERIC(20,2),
    garantia_pct        NUMERIC(10,6),
    liquidez            JSONB,                 -- {"0": v, "30": v, ...}
    prazo_vencimento    JSONB,                 -- a vencer por faixa de dias
    rating_scr          JSONB,                 -- {"AA": v, ... "H": v} por devedor
    cotas_fidc_pct      NUMERIC(10,6),         -- cotas de outros FIDCs / carteira (>= 50%: FIC-FIDC)
    cedente1_pct        NUMERIC(10,6),
    cedentes_informados INTEGER,
    condominio          TEXT,
    PRIMARY KEY (cnpj, competencia)
);
CREATE INDEX fidc_mensal_comp ON fidc_mensal (competencia);

CREATE TABLE fidc_series (
    cnpj            CHAR(14) NOT NULL REFERENCES fidcs(cnpj) ON DELETE CASCADE,
    competencia     DATE NOT NULL,
    classe_serie    TEXT NOT NULL,
    tipo            TEXT NOT NULL,             -- 'Sênior' | 'Mezanino' | 'Subordinada'
    qt_cotas        NUMERIC(28,8),
    vl_cota         NUMERIC(28,8),
    valor           NUMERIC(20,2),
    cotistas        INTEGER,
    rentab_mes      NUMERIC(12,8),
    desemp_esperado NUMERIC(12,8),
    desemp_real     NUMERIC(12,8),
    PRIMARY KEY (cnpj, competencia, classe_serie)
);

CREATE TABLE fidc_cedentes (
    cnpj          CHAR(14) NOT NULL REFERENCES fidcs(cnpj) ON DELETE CASCADE,
    competencia   DATE NOT NULL,
    ordem         SMALLINT NOT NULL,
    cnpj_cedente  CHAR(14) NOT NULL,           -- only company CNPJs are kept (CPFs dropped)
    pct           NUMERIC(10,6),
    PRIMARY KEY (cnpj, competencia, ordem)
);
CREATE INDEX fidc_cedentes_cedente ON fidc_cedentes (cnpj_cedente);

-- Names of CNPJs seen in the CVM registries (funds, classes, gestores, administradores): labels cedentes.
CREATE TABLE entidades (
    cnpj  CHAR(14) PRIMARY KEY,
    nome  TEXT NOT NULL
);

-- CVM cadastro (registro_fundo_classe.zip), one row per class CNPJ (a fund's own CNPJ when it has no class row).
-- fidcs takes gestor, administrador and the rest from here (app/ingest/cvm_fidc.apply_cadastro).
CREATE TABLE cadastro_cvm (
    cnpj               CHAR(14) PRIMARY KEY,
    origem             TEXT NOT NULL,          -- 'classe' | 'fundo'
    tipo               TEXT,                   -- Tipo_Classe / Tipo_Fundo
    nome               TEXT,
    cnpj_fundo         CHAR(14),
    nome_fundo         TEXT,
    situacao           TEXT,
    data_situacao      DATE,
    data_constituicao  DATE,
    data_registro      DATE,
    adaptacao_175      DATE,
    administrador      TEXT,
    cnpj_administrador CHAR(14),
    gestor             TEXT,
    cnpj_gestor        TEXT,
    custodiante        TEXT,
    auditor            TEXT,
    condominio         TEXT,
    exclusivo          BOOLEAN,
    publico_alvo       TEXT,
    pl                 NUMERIC(20,2),
    data_pl            DATE
);
