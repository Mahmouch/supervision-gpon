"""
=============================================================
  SUPERVISION RESEAU GPON — Setup Base de Données PostgreSQL
  Schéma : Constellation (6 dimensions) — compatible Power BI
=============================================================
  Dataset : dataset_olap_final_enriched.xlsx (6692 lignes)

  Schéma en constellation :
    DIM_GOUVERNORAT  (clé: CODGOUV)
    DIM_CENTRALE     (clé: ID_CO)
    DIM_MARQUE       (clé: NUM_MARQUE)
    DIM_OLT_CHASSIS  (clé: ID_CHSS_OLT)
    DIM_OLT_CARTE    (clé: ID_CARTE_OLT)
    DIM_TEMPS        (clé surrogate: id_temps)
    FAIT_MESURE_OLT  (clés naturelles — compatible Power BI)
=============================================================
"""

import pg8000.dbapi
import pandas as pd
from sqlalchemy import create_engine, text
import os, sys
from datetime import datetime
from urllib.parse import quote_plus

CONFIG = {
    "host":     "127.0.0.1",
    "port":     5432,
    "user":     "postgres",
    "password": "Mahmoud2004@",
    "dbname":   "supervision_gpon",
}
DATASET_PATH = "dataset_olap_final_enriched.xlsx"

GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"
BLUE="\033[94m";  RESET="\033[0m";   BOLD="\033[1m"
def log_ok(m):    print(f"{GREEN}  [OK] {m}{RESET}")
def log_info(m):  print(f"{BLUE}  -> {m}{RESET}")
def log_warn(m):  print(f"{YELLOW}  [WARN] {m}{RESET}")
def log_err(m):   print(f"{RED}  [ERR] {m}{RESET}")
def log_title(m): print(f"\n{BOLD}{BLUE}{'='*55}\n  {m}\n{'='*55}{RESET}")

def get_engine():
    pwd = quote_plus(CONFIG["password"])
    url = (f"postgresql+pg8000://{CONFIG['user']}:{pwd}"
           f"@{CONFIG['host']}:{CONFIG['port']}/{CONFIG['dbname']}")
    return create_engine(url, pool_size=5, max_overflow=10)

def _to_int(series):
    return series.where(series.isnull(), series.astype('int64').apply(int))

# ── ETAPE 1 ──────────────────────────────────────────────────
def create_database():
    log_title("ETAPE 1 — Création de la base de données")
    try:
        conn = pg8000.dbapi.connect(
            host=CONFIG["host"], port=CONFIG["port"],
            user=CONFIG["user"], password=CONFIG["password"],
            database="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (CONFIG["dbname"],))
        if cur.fetchone():
            log_warn(f"Base '{CONFIG['dbname']}' existe déjà — on continue.")
        else:
            cur.execute(f"CREATE DATABASE {CONFIG['dbname']} ENCODING 'UTF8'")
            log_ok(f"Base '{CONFIG['dbname']}' créée.")
        cur.close(); conn.close()
    except Exception as e:
        log_err(f"Impossible de se connecter : {e}"); sys.exit(1)

# ── ETAPE 2 ──────────────────────────────────────────────────
SQL_DROP = """
DROP TABLE IF EXISTS fait_mesure_olt     CASCADE;
DROP TABLE IF EXISTS prediction_anomalie CASCADE;
DROP TABLE IF EXISTS log_incidents       CASCADE;
DROP TABLE IF EXISTS dim_olt_carte       CASCADE;
DROP TABLE IF EXISTS dim_olt_chassis     CASCADE;
DROP TABLE IF EXISTS dim_marque          CASCADE;
DROP TABLE IF EXISTS dim_centrale        CASCADE;
DROP TABLE IF EXISTS dim_gouvernorat     CASCADE;
DROP TABLE IF EXISTS dim_temps           CASCADE;
"""

SQL_CREATE = """
CREATE TABLE IF NOT EXISTS dim_gouvernorat (
    codgouv     SMALLINT    PRIMARY KEY,
    gouvernorat VARCHAR(50) NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_centrale (
    id_co       INTEGER      PRIMARY KEY,
    centrale    VARCHAR(100) NOT NULL,
    codgouv     SMALLINT     REFERENCES dim_gouvernorat(codgouv),
    gouvernorat VARCHAR(50)
);
CREATE TABLE IF NOT EXISTS dim_marque (
    num_marque  INTEGER     PRIMARY KEY,
    marque      VARCHAR(50) NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_olt_chassis (
    id_chss_olt INTEGER      PRIMARY KEY,
    host_name   VARCHAR(100),
    centrale    VARCHAR(100),
    codgouv     SMALLINT,
    gouvernorat VARCHAR(50),
    id_co       INTEGER      REFERENCES dim_centrale(id_co),
    marque      VARCHAR(50),
    num_marque  INTEGER      REFERENCES dim_marque(num_marque)
);
CREATE TABLE IF NOT EXISTS dim_olt_carte (
    id_carte_olt INTEGER  PRIMARY KEY,
    id_chss_olt  INTEGER  REFERENCES dim_olt_chassis(id_chss_olt),
    slot_no      SMALLINT,
    type_carte   INTEGER
);
CREATE TABLE IF NOT EXISTS dim_temps (
    id_temps    SERIAL     PRIMARY KEY,
    date_mesure TIMESTAMP  UNIQUE NOT NULL,
    date_seule  DATE,
    annee       SMALLINT,
    trimestre   SMALLINT,
    mois        SMALLINT,
    nom_mois    VARCHAR(20),
    jour        SMALLINT,
    heure       SMALLINT
);
CREATE TABLE IF NOT EXISTS fait_mesure_olt (
    id_fait          SERIAL   PRIMARY KEY,
    id_ligne         INTEGER  NOT NULL,
    id_temps         INTEGER  REFERENCES dim_temps(id_temps),
    codgouv          SMALLINT REFERENCES dim_gouvernorat(codgouv),
    id_co            INTEGER  REFERENCES dim_centrale(id_co),
    id_chss_olt      INTEGER  REFERENCES dim_olt_chassis(id_chss_olt),
    id_carte_olt     INTEGER  REFERENCES dim_olt_carte(id_carte_olt),
    no_port          SMALLINT,
    onu_id           SMALLINT,
    admin_status     SMALLINT,
    oper_status      SMALLINT,
    f_susp           SMALLINT,
    olt_power_tx     FLOAT,
    olt_rx_ont_power FLOAT,
    onu_power_tx     FLOAT,
    onu_power_rx     FLOAT,
    qualite_signal   VARCHAR(20),
    anomalie_technique  SMALLINT DEFAULT NULL,
    anomalie_admin      SMALLINT DEFAULT NULL,
    anomalie            SMALLINT DEFAULT NULL,
    ml_anomalie_pred    SMALLINT DEFAULT NULL,
    ml_anomalie_score   FLOAT    DEFAULT NULL,
    ml_cluster          SMALLINT DEFAULT NULL,
    ml_type_anomalie    VARCHAR(100) DEFAULT NULL,
    ml_predicted_at     TIMESTAMP   DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS prediction_anomalie (
    id_prediction          SERIAL    PRIMARY KEY,
    id_ligne               INTEGER,
    date_mesure            TIMESTAMP,
    score_isolation_forest FLOAT,
    label_isolation_forest SMALLINT,
    score_zscore           FLOAT,
    label_zscore           SMALLINT,
    label_binaire          SMALLINT,
    anomalie_finale        SMALLINT,
    cluster                SMALLINT,
    predicted_at           TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS log_incidents (
    id_incident      SERIAL    PRIMARY KEY,
    id_ligne         INTEGER,
    date_mesure      TIMESTAMP,
    olt_power_tx     FLOAT,
    olt_rx_ont_power FLOAT,
    onu_power_tx     FLOAT,
    onu_power_rx     FLOAT,
    f_susp           SMALLINT,
    admin_status     SMALLINT,
    oper_status      SMALLINT,
    score_zscore     FLOAT,
    severite         VARCHAR(20),   -- 'CRITIQUE' ou 'MODERE'
    source           VARCHAR(50),   -- 'IF', 'ZSCORE', 'IF+ZSCORE', etc.
    statut           VARCHAR(20)    DEFAULT 'DETECTE',
    detected_at      TIMESTAMP      DEFAULT NOW(),
    resolved_at      TIMESTAMP      DEFAULT NULL,
    commentaire      TEXT           DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS clustering_result (
    id_cluster       SERIAL    PRIMARY KEY,
    id_ligne         INTEGER   NOT NULL,
    date_mesure      TIMESTAMP,
    cluster_id       SMALLINT,
    groupe           VARCHAR(50),
    card_fault_rate  FLOAT,
    port_fault_rate  FLOAT,
    cause            VARCHAR(100)
);
"""

def create_tables(engine):
    log_title("ETAPE 2 — Suppression et recréation (constellation)")
    with engine.connect() as conn:
        conn.execute(text(SQL_DROP));  conn.commit()
        log_info("Anciennes tables supprimées.")
        conn.execute(text(SQL_CREATE)); conn.commit()
    log_ok("dim_gouvernorat  (clé: CODGOUV)")
    log_ok("dim_centrale     (clé: ID_CO)")
    log_ok("dim_marque       (clé: NUM_MARQUE)")
    log_ok("dim_olt_chassis  (clé: ID_CHSS_OLT)")
    log_ok("dim_olt_carte    (clé: ID_CARTE_OLT)")
    log_ok("dim_temps        (clé surrogate: id_temps)")
    log_ok("fait_mesure_olt  (table centrale — clés naturelles)")
    log_ok("prediction_anomalie + log_incidents")

# ── ETAPE 3 ──────────────────────────────────────────────────
def load_dataset(engine):
    log_title("ETAPE 3 — Chargement du dataset")
    if not os.path.exists(DATASET_PATH):
        log_err(f"Fichier introuvable : {DATASET_PATH}"); sys.exit(1)

    log_info(f"Lecture de {DATASET_PATH} ...")
    df = pd.read_excel(DATASET_PATH)
    log_ok(f"Dataset : {df.shape[0]} lignes × {df.shape[1]} colonnes")

    df['GOUVERNORAT'] = df['GOUVERNORAT'].str.strip()
    df['CENTRALE']    = df['CENTRALE'].str.strip()
    df['DATE_MESURE'] = pd.to_datetime(df['DATE_MESURE'])
    df['DATE_SEULE']  = pd.to_datetime(df['DATE_SEULE'])

    # 1. dim_gouvernorat
    log_info("dim_gouvernorat ...")
    d = df[['CODGOUV','GOUVERNORAT']].drop_duplicates('CODGOUV').copy()
    d.columns = ['codgouv','gouvernorat']
    d['codgouv'] = _to_int(d['codgouv'])
    d.to_sql('dim_gouvernorat', engine, if_exists='append', index=False)
    log_ok(f"dim_gouvernorat : {len(d)} lignes")

    # 2. dim_centrale
    log_info("dim_centrale ...")
    d = df[['ID_CO','CENTRALE','CODGOUV','GOUVERNORAT']].drop_duplicates('ID_CO').copy()
    d.columns = ['id_co','centrale','codgouv','gouvernorat']
    d['id_co'] = _to_int(d['id_co']); d['codgouv'] = _to_int(d['codgouv'])
    d.to_sql('dim_centrale', engine, if_exists='append', index=False)
    log_ok(f"dim_centrale : {len(d)} lignes")

    # 3. dim_marque
    log_info("dim_marque ...")
    d = df[['NUM_MARQUE','MARQUE']].drop_duplicates('NUM_MARQUE').copy()
    d.columns = ['num_marque','marque']
    d['num_marque'] = _to_int(d['num_marque'])
    d.to_sql('dim_marque', engine, if_exists='append', index=False)
    log_ok(f"dim_marque : {len(d)} lignes")

    # 4. dim_olt_chassis
    log_info("dim_olt_chassis ...")
    d = df[['ID_CHSS_OLT','HOST_NAME','CENTRALE','CODGOUV','GOUVERNORAT','ID_CO','MARQUE','NUM_MARQUE']].drop_duplicates('ID_CHSS_OLT').copy()
    d.columns = ['id_chss_olt','host_name','centrale','codgouv','gouvernorat','id_co','marque','num_marque']
    for c in ['id_chss_olt','codgouv','id_co','num_marque']: d[c] = _to_int(d[c])
    d.to_sql('dim_olt_chassis', engine, if_exists='append', index=False)
    log_ok(f"dim_olt_chassis : {len(d)} lignes")

    # 5. dim_olt_carte
    log_info("dim_olt_carte ...")
    d = df[['ID_CARTE_OLT','ID_CHSS_OLT','SLOT_NO','TYPE_CARTE']].drop_duplicates('ID_CARTE_OLT').copy()
    d.columns = ['id_carte_olt','id_chss_olt','slot_no','type_carte']
    for c in ['id_carte_olt','id_chss_olt','slot_no','type_carte']: d[c] = _to_int(d[c])
    d.to_sql('dim_olt_carte', engine, if_exists='append', index=False)
    log_ok(f"dim_olt_carte : {len(d)} lignes")

    # 6. dim_temps
    log_info("dim_temps ...")
    d = df[['DATE_MESURE','DATE_SEULE','ANNEE','TRIMESTRE','MOIS','NOM_MOIS','JOUR','HEURE']].drop_duplicates('DATE_MESURE').copy()
    d.columns = [c.lower() for c in d.columns]
    for c in ['annee','trimestre','mois','jour','heure']: d[c] = _to_int(d[c])
    d['date_mesure'] = d['date_mesure'].apply(lambda x: x.to_pydatetime() if pd.notna(x) else None)
    d['date_seule']  = d['date_seule'].apply(lambda x: x.date() if pd.notna(x) else None)
    d.to_sql('dim_temps', engine, if_exists='append', index=False, chunksize=500)
    log_ok(f"dim_temps : {len(d)} lignes")

    # 7. fait_mesure_olt
    log_info("Résolution id_temps et insertion fait_mesure_olt ...")
    with engine.connect() as conn:
        dim_t = pd.read_sql("SELECT id_temps, date_mesure FROM dim_temps", conn)

    df_f = df.copy()
    df_f.columns = [c.lower() for c in df_f.columns]
    dim_t['date_mesure'] = pd.to_datetime(dim_t['date_mesure'])
    df_f['date_mesure']  = pd.to_datetime(df_f['date_mesure'])
    df_f = df_f.merge(dim_t, on='date_mesure', how='left')

    cols = ['id_ligne','id_temps','codgouv','id_co','id_chss_olt','id_carte_olt',
            'no_port','onu_id','admin_status','oper_status','f_susp',
            'olt_power_tx','olt_rx_ont_power','onu_power_tx','onu_power_rx','qualite_signal']
    df_f = df_f[[c for c in cols if c in df_f.columns]].copy()
    for c in ['id_ligne','id_temps','codgouv','id_co','id_chss_olt','id_carte_olt',
              'no_port','onu_id','admin_status','oper_status','f_susp']:
        if c in df_f.columns: df_f[c] = _to_int(df_f[c])

    fks = {'id_temps':'dim_temps','codgouv':'dim_gouvernorat','id_co':'dim_centrale',
           'id_chss_olt':'dim_olt_chassis','id_carte_olt':'dim_olt_carte'}
    for fk, tbl in fks.items():
        nb = df_f[fk].isnull().sum() if fk in df_f.columns else 0
        (log_warn if nb > 0 else log_ok)(f"{fk} ({tbl}) : {nb} nulls")

    df_f.to_sql('fait_mesure_olt', engine, if_exists='append', index=False, chunksize=500)
    log_ok(f"fait_mesure_olt : {len(df_f)} lignes insérées")

# ── ETAPE 4 ──────────────────────────────────────────────────
SQL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fait_temps      ON fait_mesure_olt(id_temps);
CREATE INDEX IF NOT EXISTS idx_fait_codgouv    ON fait_mesure_olt(codgouv);
CREATE INDEX IF NOT EXISTS idx_fait_id_co      ON fait_mesure_olt(id_co);
CREATE INDEX IF NOT EXISTS idx_fait_chassis    ON fait_mesure_olt(id_chss_olt);
CREATE INDEX IF NOT EXISTS idx_fait_carte      ON fait_mesure_olt(id_carte_olt);
CREATE INDEX IF NOT EXISTS idx_fait_qualite    ON fait_mesure_olt(qualite_signal);
CREATE INDEX IF NOT EXISTS idx_fait_anomalie   ON fait_mesure_olt(anomalie);
CREATE INDEX IF NOT EXISTS idx_fait_ml_pred    ON fait_mesure_olt(ml_anomalie_pred);
CREATE INDEX IF NOT EXISTS idx_temps_date      ON dim_temps(date_seule);
CREATE INDEX IF NOT EXISTS idx_temps_mois      ON dim_temps(mois, annee);
CREATE INDEX IF NOT EXISTS idx_gouv_nom        ON dim_gouvernorat(gouvernorat);
CREATE INDEX IF NOT EXISTS idx_chassis_host    ON dim_olt_chassis(host_name);
CREATE INDEX IF NOT EXISTS idx_pred_finale     ON prediction_anomalie(anomalie_finale);
"""

def create_indexes(engine):
    log_title("ETAPE 4 — Création des index")
    with engine.connect() as conn:
        conn.execute(text(SQL_INDEXES)); conn.commit()
    log_ok("13 index créés")

# ── ETAPE 5 ──────────────────────────────────────────────────
def verify(engine):
    log_title("ETAPE 5 — Vérification")
    queries = [
        ("Comptage par table", """
            SELECT 'dim_gouvernorat' AS t, COUNT(*) n FROM dim_gouvernorat UNION ALL
            SELECT 'dim_centrale',         COUNT(*) FROM dim_centrale      UNION ALL
            SELECT 'dim_marque',           COUNT(*) FROM dim_marque        UNION ALL
            SELECT 'dim_olt_chassis',      COUNT(*) FROM dim_olt_chassis   UNION ALL
            SELECT 'dim_olt_carte',        COUNT(*) FROM dim_olt_carte     UNION ALL
            SELECT 'dim_temps',            COUNT(*) FROM dim_temps         UNION ALL
            SELECT 'fait_mesure_olt',      COUNT(*) FROM fait_mesure_olt   ORDER BY t"""),
        ("FK nulles (0 attendu partout)", """
            SELECT
              SUM(CASE WHEN id_temps     IS NULL THEN 1 ELSE 0 END) null_temps,
              SUM(CASE WHEN codgouv      IS NULL THEN 1 ELSE 0 END) null_codgouv,
              SUM(CASE WHEN id_co        IS NULL THEN 1 ELSE 0 END) null_id_co,
              SUM(CASE WHEN id_chss_olt  IS NULL THEN 1 ELSE 0 END) null_chassis,
              SUM(CASE WHEN id_carte_olt IS NULL THEN 1 ELSE 0 END) null_carte
            FROM fait_mesure_olt"""),
        ("Qualité signal", "SELECT qualite_signal, COUNT(*) n FROM fait_mesure_olt GROUP BY 1 ORDER BY 2 DESC"),
        ("Top gouvernorats", """
            SELECT g.gouvernorat, COUNT(*) n, ROUND(AVG(f.olt_rx_ont_power)::numeric,3) moy_rx
            FROM fait_mesure_olt f JOIN dim_gouvernorat g ON f.codgouv=g.codgouv
            GROUP BY 1 ORDER BY 2 DESC LIMIT 5"""),
    ]
    with engine.connect() as conn:
        for label, q in queries:
            print(f"\n  {BLUE}{label}{RESET}")
            try:
                print(pd.read_sql(q, conn).to_string(index=False)); log_ok("OK")
            except Exception as e:
                log_warn(f"Erreur : {e}")

# ── UTILITAIRES ───────────────────────────────────────────────
def insert_ml_results(id_ligne, anomalie_pred, score, cluster, type_anomalie):
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            UPDATE fait_mesure_olt SET
                ml_anomalie_pred=:pred, ml_anomalie_score=:score,
                ml_cluster=:cluster, ml_type_anomalie=:type_a, ml_predicted_at=NOW()
            WHERE id_ligne=:id_ligne
        """), {"pred":int(anomalie_pred),"score":float(score),
               "cluster":int(cluster),"type_a":type_anomalie,"id_ligne":int(id_ligne)})
        conn.commit()

def get_rollup_mensuel():
    eng = get_engine()
    with eng.connect() as conn:
        return pd.read_sql("""
            SELECT t.annee, t.mois, t.nom_mois, g.gouvernorat, m.marque,
                COUNT(*) total, ROUND(AVG(f.olt_rx_ont_power)::numeric,3) moy_rx,
                COUNT(CASE WHEN f.qualite_signal='MAUVAIS' THEN 1 END) nb_mauvais,
                COUNT(CASE WHEN f.ml_anomalie_pred=1       THEN 1 END) nb_anomalies_ml
            FROM fait_mesure_olt f
            JOIN dim_temps       t  ON f.id_temps    = t.id_temps
            JOIN dim_gouvernorat g  ON f.codgouv     = g.codgouv
            JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
            JOIN dim_marque      m  ON ch.num_marque = m.num_marque
            GROUP BY t.annee,t.mois,t.nom_mois,g.gouvernorat,m.marque
            ORDER BY t.annee,t.mois
        """, conn)

# ── MAIN ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{BOLD}  SUPERVISION RESEAU GPON — Setup PostgreSQL{RESET}")
    print(f"  Schéma constellation — compatible Power BI")
    print(f"  Démarré le {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}\n")
    create_database()
    engine = get_engine()
    create_tables(engine)
    load_dataset(engine)
    create_indexes(engine)
    verify(engine)
    print(f"\n{BOLD}{GREEN}  [OK] Setup terminé !{RESET}")
    print(f"  Prochaine étape -> python cube_rolap.py\n")