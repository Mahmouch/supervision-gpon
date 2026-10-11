from sqlalchemy import text
from db_setup import get_engine

def create_views():
    engine = get_engine()
    with engine.connect() as conn:
        print("Alignement des vues SQL avec le rapport (Tableau 3.4)...")
        
        # 1. v_supervision (Granularité: une ligne par mesure)
        conn.execute(text("""
            DROP VIEW IF EXISTS v_supervision CASCADE;
            CREATE VIEW v_supervision AS
            SELECT 
                f.id_fait,
                t.date_seule,
                t.heure,
                g.gouvernorat,
                c.centrale,
                ch.host_name,
                ch.marque,
                f.olt_rx_ont_power as puissance_rx_olt,
                f.onu_power_rx as puissance_rx_onu,
                f.qualite_signal,
                f.ml_anomalie_pred as anomalie, -- Alias pour PowerBI
                f.ml_anomalie_pred as ml_anomalie_pred,
                f.ml_cluster,
                f.ml_type_anomalie as ml_type_anomalie,
                f.ml_type_anomalie as type_anomalie, -- Alias pour PowerBI
                CASE WHEN f.ml_type_anomalie != 'ADMIN' THEN f.ml_anomalie_pred ELSE 0 END as anomalie_technique,
                CASE WHEN f.ml_type_anomalie = 'ADMIN' THEN f.ml_anomalie_pred ELSE 0 END as anomalie_admin,
                f.ml_anomalie_score
            FROM fait_mesure_olt f
            LEFT JOIN dim_temps t ON f.id_temps = t.id_temps
            LEFT JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            LEFT JOIN dim_centrale c ON f.id_co = c.id_co
            LEFT JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
        """))
        
        # 2. v_anomalies_mensuel (Granularité: Agrégation mois/gouv/centrale/marque)
        conn.execute(text("""
            DROP VIEW IF EXISTS v_anomalies_mensuel CASCADE;
            CREATE VIEW v_anomalies_mensuel AS
            SELECT 
                t.annee,
                t.mois,
                t.nom_mois,
                g.gouvernorat,
                c.centrale,
                ch.marque,
                COUNT(*) as total_mesures,
                SUM(f.ml_anomalie_pred) as nb_anomalies,
                SUM(f.ml_anomalie_pred) as anomalie, -- Alias
                ROUND(CAST(SUM(f.ml_anomalie_pred) AS NUMERIC) / COUNT(*) * 100, 2) as taux_anomalie,
                ROUND(CAST(AVG(f.ml_anomalie_score) AS NUMERIC), 4) as score_moyen
            FROM fait_mesure_olt f
            JOIN dim_temps t ON f.id_temps = t.id_temps
            JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            JOIN dim_centrale c ON f.id_co = c.id_co
            JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
            GROUP BY t.annee, t.mois, t.nom_mois, g.gouvernorat, c.centrale, ch.marque
        """))
        
        # 3. v_clusters (Granularité: Agrégation par groupe K-Means)
        conn.execute(text("""
            DROP VIEW IF EXISTS v_clusters CASCADE;
            CREATE VIEW v_clusters AS
            SELECT 
                ml_cluster as cluster_id,
                ml_type_anomalie as groupe,
                COUNT(*) as nb_anomalies,
                ROUND(CAST(AVG(olt_rx_ont_power) AS NUMERIC), 2) as moy_olt_rx,
                ROUND(CAST(AVG(onu_power_rx) AS NUMERIC), 2) as moy_onu_rx,
                MAX(ml_type_anomalie) as cause_principale
            FROM fait_mesure_olt
            WHERE ml_anomalie_pred = 1
            GROUP BY ml_cluster, ml_type_anomalie
        """))
        
        conn.commit()
        print("Vues SQL synchronisées avec le rapport ISIM SFAX.")

if __name__ == "__main__":
    create_views()
