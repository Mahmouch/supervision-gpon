"""
inject_ml.py
Injecte les résultats ML dans PostgreSQL :
  - PREDICTION_ANOMALIE.xlsx → table prediction_anomalie
  - LOG_INCIDENTS.xlsx       → table log_incidents
  - CLUSTERING_RESULT.xlsx   → table clustering_result
  - Met à jour fait_mesure_olt avec les scores/labels
"""

import pandas as pd
from sqlalchemy import text
from db_setup import get_engine

def _to_int(series):
    return series.where(series.isnull(), series.astype('int64').apply(int))

# ── 1. PREDICTION_ANOMALIE ────────────────────────────────────
def inject_predictions(engine):
    print("\n-> Injection PREDICTION_ANOMALIE ...")
    df = pd.read_excel('PREDICTION_ANOMALIE.xlsx')
    print(f"  {len(df)} lignes | {df['anomalie_finale'].sum()} anomalies")

    df_db = df[[
        'ID_LIGNE', 'DATE_MESURE',
        'score_isolation_forest', 'label_isolation_forest',
        'score_zscore', 'label_zscore',
        'label_binaire', 'anomalie_finale'
    ]].copy()
    df_db.columns = [c.lower() for c in df_db.columns]
    df_db['date_mesure'] = pd.to_datetime(df_db['date_mesure']).apply(
        lambda x: x.to_pydatetime() if pd.notna(x) else None)
    for col in ['id_ligne', 'label_isolation_forest',
                'label_zscore', 'label_binaire', 'anomalie_finale']:
        df_db[col] = _to_int(df_db[col])

    df_db.to_sql('prediction_anomalie', engine,
                 if_exists='append', index=False, chunksize=500)
    print(f"  [OK] prediction_anomalie : {len(df_db)} lignes insérées")

# ── 2. LOG_INCIDENTS ─────────────────────────────────────────
def inject_incidents(engine):
    print("\n-> Injection LOG_INCIDENTS ...")
    df = pd.read_excel('LOG_INCIDENTS.xlsx')
    print(f"  {len(df)} incidents | {df['SEVERITE'].value_counts().to_dict()}")

    df_db = df[[
        'ID_LIGNE', 'DATE_MESURE',
        'OLT_POWER_TX', 'OLT_RX_ONT_POWER', 'ONU_POWER_TX', 'ONU_POWER_RX',
        'F_SUSP', 'ADMIN_STATUS', 'OPER_STATUS',
        'score_zscore', 'SEVERITE', 'SOURCE', 'STATUT'
    ]].copy()
    df_db.columns = [c.lower() for c in df_db.columns]
    df_db['date_mesure'] = pd.to_datetime(df_db['date_mesure']).apply(
        lambda x: x.to_pydatetime() if pd.notna(x) else None)
    for col in ['id_ligne', 'f_susp', 'admin_status', 'oper_status']:
        df_db[col] = _to_int(df_db[col])

    df_db.to_sql('log_incidents', engine,
                 if_exists='append', index=False, chunksize=500)
    print(f"  [OK] log_incidents : {len(df_db)} lignes insérées")

# ── 3. CLUSTERING_RESULT ─────────────────────────────────────
def inject_clustering(engine):
    print("\n-> Injection CLUSTERING_RESULT ...")
    df = pd.read_excel('CLUSTERING_RESULT.xlsx')
    print(f"  {len(df)} anomalies clusterisées")
    print(f"  Groupes : {df['groupe'].value_counts().to_dict()}")

    df_db = df[[
        'ID_LIGNE', 'DATE_MESURE',
        'cluster_id', 'groupe',
        'card_fault_rate', 'port_fault_rate', 'Cause'
    ]].copy()
    df_db.columns = ['id_ligne', 'date_mesure', 'cluster_id',
                     'groupe', 'card_fault_rate', 'port_fault_rate', 'cause']
    df_db['date_mesure'] = pd.to_datetime(df_db['date_mesure']).apply(
        lambda x: x.to_pydatetime() if pd.notna(x) else None)
    df_db['id_ligne']    = _to_int(df_db['id_ligne'])
    df_db['cluster_id']  = _to_int(df_db['cluster_id'])

    df_db.to_sql('clustering_result', engine,
                 if_exists='append', index=False, chunksize=500)
    print(f"  [OK] clustering_result : {len(df_db)} lignes insérées")

# ── 4. MISE À JOUR fait_mesure_olt ───────────────────────────
def update_fait_mesure_olt(engine):
    print("\n-> Mise à jour fait_mesure_olt avec résultats ML ...")

    # Lire les deux sources ML
    df_pred = pd.read_excel('PREDICTION_ANOMALIE.xlsx')[[
        'ID_LIGNE', 'score_isolation_forest', 'label_isolation_forest',
        'anomalie_finale'
    ]]
    df_clust = pd.read_excel('CLUSTERING_RESULT.xlsx')[[
        'ID_LIGNE', 'cluster_id', 'groupe', 'Cause'
    ]]

    # Joindre les deux
    df = df_pred.merge(df_clust, on='ID_LIGNE', how='left')

    with engine.connect() as conn:
        for _, row in df.iterrows():
            conn.execute(text("""
                UPDATE fait_mesure_olt SET
                    ml_anomalie_pred  = :pred,
                    ml_anomalie_score = :score,
                    ml_cluster        = :cluster,
                    ml_type_anomalie  = :cause,
                    ml_predicted_at   = NOW()
                WHERE id_ligne = :id_ligne
            """), {
                "pred":     int(row['anomalie_finale']),
                "score":    float(row['score_isolation_forest']),
                "cluster":  int(row['cluster_id'])
                             if pd.notna(row.get('cluster_id')) else None,
                "cause":    str(row['Cause'])
                             if pd.notna(row.get('Cause')) else None,
                "id_ligne": int(row['ID_LIGNE']),
            })
        conn.commit()

    total     = len(df)
    anomalies = int(df['anomalie_finale'].sum())
    print(f"  [OK] {total} lignes mises à jour")
    print(f"  [OK] {anomalies} anomalies | {total - anomalies} normales")

# ── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = get_engine()
    inject_predictions(engine)
    inject_incidents(engine)
    inject_clustering(engine)
    update_fait_mesure_olt(engine)
    print("\n[OK] Injection ML complète — BD prête pour le cube ROLAP")