from sqlalchemy import create_engine, text
engine = create_engine('postgresql+pg8000://postgres:Mahmoud2004%40@localhost:5432/supervision_gpon')
with engine.begin() as conn:
    res = conn.execute(text("UPDATE fait_mesure_olt SET anomalie_admin = 1, anomalie_technique = 0 WHERE f_susp = 1 OR (admin_status = 0 AND oper_status = 1) OR ml_cluster = 2"))
    print(f"Update done, rows affected: {res.rowcount}")
