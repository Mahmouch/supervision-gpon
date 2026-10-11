"""
redistribute_temps.py
Redistribue les timestamps de dim_temps sur 90 jours (Jan-Mar 2026)
pour simuler une collecte réaliste d'un réseau GPON.
Ne touche PAS aux valeurs métier (puissance, anomalies, clusters).
"""
import random
import math
from datetime import datetime, timedelta, date
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+pg8000://postgres:Mahmoud2004%40@localhost:5432/supervision_gpon')

# ── Paramètres ──────────────────────────────────────────────
START_DATE = date(2026, 1, 1)
END_DATE   = date(2026, 3, 27)
TOTAL_DAYS = (END_DATE - START_DATE).days + 1  # 86 jours

# Poids journaliers : plus actif en semaine (lundi=0..vendredi=4), moins le week-end
WEEKDAY_WEIGHT = [1.4, 1.3, 1.2, 1.3, 1.1, 0.6, 0.4]  # Lun..Dim

# Poids horaires : pics à 9h, 14h, 18h (collectes planifiées)
HOUR_WEIGHTS = {
    0:0.1, 1:0.1, 2:0.1, 3:0.1, 4:0.2, 5:0.3,
    6:0.5, 7:0.9, 8:1.3, 9:1.8, 10:1.6, 11:1.4,
    12:0.8, 13:1.0, 14:1.7, 15:1.5, 16:1.3, 17:1.2,
    18:1.6, 19:1.1, 20:0.8, 21:0.6, 22:0.3, 23:0.2
}

random.seed(42)

# ── Récupérer tous les id_temps triés ────────────────────────
print("📥 Récupération des id_temps...")
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT id_temps FROM dim_temps ORDER BY date_mesure ASC"
    )).fetchall()

id_list = [r[0] for r in rows]
N = len(id_list)
print(f"   → {N} entrées à redistribuer sur {TOTAL_DAYS} jours")

# ── Construire la distribution : nb de mesures par jour ──────
days = [START_DATE + timedelta(days=i) for i in range(TOTAL_DAYS)]

# Poids composites (jour_semaine × légère variation aléatoire)
raw_weights = []
for d in days:
    w = WEEKDAY_WEIGHT[d.weekday()]
    w *= random.uniform(0.7, 1.3)  # variation aléatoire naturelle
    raw_weights.append(w)

total_w = sum(raw_weights)
counts = []
assigned = 0
for i, w in enumerate(raw_weights):
    if i == len(raw_weights) - 1:
        counts.append(N - assigned)
    else:
        c = max(1, round(N * w / total_w))
        counts.append(c)
        assigned += c

# Ajustement si la somme dépasse N
while sum(counts) > N:
    idx = random.randint(0, len(counts)-1)
    if counts[idx] > 1:
        counts[idx] -= 1
while sum(counts) < N:
    idx = random.randint(0, len(counts)-1)
    counts[idx] += 1

print(f"   → Vérification : {sum(counts)} == {N} ✓")

# ── Générer les nouveaux timestamps ──────────────────────────
print("🕐 Génération des timestamps réalistes...")
new_timestamps = []
for day, count in zip(days, counts):
    # Choisir 'count' heures selon les poids horaires
    hours_pool = list(HOUR_WEIGHTS.keys())
    hour_w     = [HOUR_WEIGHTS[h] for h in hours_pool]

    for _ in range(count):
        h  = random.choices(hours_pool, weights=hour_w, k=1)[0]
        m  = random.randint(0, 59)
        s  = random.randint(0, 59)
        us = random.randint(0, 999999)
        ts = datetime(day.year, day.month, day.day, h, m, s, us)
        new_timestamps.append(ts)

# Trier pour cohérence (optionnel mais propre)
new_timestamps.sort()

# ── Mise à jour de la base ────────────────────────────────────
print("💾 Mise à jour de dim_temps...")
MOIS_FR = {
    1:'Janvier', 2:'Février', 3:'Mars', 4:'Avril',
    5:'Mai', 6:'Juin', 7:'Juillet', 8:'Août',
    9:'Septembre', 10:'Octobre', 11:'Novembre', 12:'Décembre'
}

with engine.begin() as conn:
    for i, (id_t, ts) in enumerate(zip(id_list, new_timestamps)):
        conn.execute(text("""
            UPDATE dim_temps SET
                date_mesure = :dm,
                date_seule  = :ds,
                annee       = :a,
                trimestre   = :tr,
                mois        = :mo,
                nom_mois    = :nm,
                jour        = :j,
                heure       = :h
            WHERE id_temps = :id
        """), {
            "dm": ts,
            "ds": ts.date(),
            "a":  ts.year,
            "tr": math.ceil(ts.month / 3),
            "mo": ts.month,
            "nm": MOIS_FR[ts.month],
            "j":  ts.day,
            "h":  ts.hour,
            "id": id_t
        })
        if (i+1) % 500 == 0:
            print(f"   → {i+1}/{N} mis à jour...")

print(f"\n✅ Redistribution terminée ! {N} entrées mises à jour.")
print(f"   Période : {START_DATE} → {END_DATE}")
print(f"   Moyenne : {N//TOTAL_DAYS} mesures/jour")

# ── Vérification rapide ───────────────────────────────────────
print("\n📊 Aperçu par mois :")
with engine.connect() as conn:
    check = conn.execute(text("""
        SELECT nom_mois, mois, COUNT(*) as total, SUM(f.anomalie) as anomalies
        FROM dim_temps t
        JOIN fait_mesure_olt f ON t.id_temps = f.id_temps
        GROUP BY nom_mois, mois
        ORDER BY mois
    """)).fetchall()
    for r in check:
        print(f"   {r[0]:12s} → {r[2]:4d} mesures, {int(r[3] or 0)} anomalies")
