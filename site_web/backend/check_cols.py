from sqlalchemy import create_engine, text
engine = create_engine('postgresql+pg8000://postgres:Mahmoud2004%40@localhost:5432/supervision_gpon')
with engine.connect() as conn:
    res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'fait_mesure_olt'"))
    for r in res:
        print(r[0])
