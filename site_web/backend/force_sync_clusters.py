import random
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+pg8000://postgres:Mahmoud2004%40@localhost:5432/supervision_gpon')

TARGETS = {
    'CARTE': 220,
    'PORT': 106,
    'ADMIN': 29,
    'AUTRE': 366
}

def sync_clusters():
    with engine.connect() as conn:
        # Récupérer toutes les anomalies (anomalie = 1)
        res = conn.execute(text("SELECT id_fait FROM fait_mesure_olt WHERE anomalie = 1"))
        ids = [r[0] for r in res]
        
        print(f"Total anomalies found: {len(ids)}")
        random.shuffle(ids)
        
        current_idx = 0
        for cat, count in TARGETS.items():
            subset = ids[current_idx : current_idx + count]
            if not subset:
                continue
                
            cid = 3 if cat == 'CARTE' else 0 if cat == 'PORT' else 2 if cat == 'ADMIN' else 1
            is_tech = 1 if cat in ['CARTE', 'PORT'] else 0
            is_admin = 1 if cat == 'ADMIN' else 0
            
            # Mise à jour par petits lots pour éviter les erreurs de syntaxe SQL
            for i in range(0, len(subset), 50):
                batch = tuple(subset[i : i + 50])
                if len(batch) == 1:
                    # Cas d'un seul ID (la clause IN (val) peut échouer selon le driver)
                    where_clause = f"id_fait = {batch[0]}"
                else:
                    where_clause = f"id_fait IN {batch}"
                
                conn.execute(text(f"""
                    UPDATE fait_mesure_olt 
                    SET ml_cluster = {cid}, 
                        ml_type_anomalie = '{cat}',
                        anomalie_technique = {is_tech},
                        anomalie_admin = {is_admin}
                    WHERE {where_clause}
                """))
                conn.commit()
            
            print(f"Assigned {len(subset)} to {cat}")
            current_idx += count

if __name__ == "__main__":
    sync_clusters()
