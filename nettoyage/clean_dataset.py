"""
clean_dataset.py
================
Phase 1 : Nettoyage du dataset OLAP avant chargement PostgreSQL.

Operations effectuees :
  1. Categorisation des lignes (ACTIF / INACTIF / DONNEE_MANQUANTE)
  2. Marquage des outliers physiques (methode IQR)
  3. Correction de la divergence geographique
  4. Detection et suppression des doublons
  5. Validation finale et rapport de qualite

Entree  : olap_dataset_final.xlsx (feuille FAIT_MESURE_OLT)
Sortie  : olap_clean.xlsx (toutes les feuilles du schema)
"""

import pandas as pd
import numpy as np
import os

FEATURES = ['olt_power_tx', 'olt_rx_ont_power', 'onu_power_tx', 'onu_power_rx']

INPUT_FILE  = "olap_dataset_final.xlsx"
OUTPUT_FILE = "olap_clean.xlsx"

SEP = "=" * 58

# ─────────────────────────────────────────────────────────────
# CHARGEMENT
# ─────────────────────────────────────────────────────────────
print(SEP)
print("  CHARGEMENT DE olap_dataset_final.xlsx")
print(SEP)

df       = pd.read_excel(INPUT_FILE, sheet_name="FAIT_MESURE_OLT")
dim_equip = pd.read_excel(INPUT_FILE, sheet_name="DIM_EQUIPEMENT")
dim_geo   = pd.read_excel(INPUT_FILE, sheet_name="DIM_GEOGRAPHIE")
dim_temps = pd.read_excel(INPUT_FILE, sheet_name="DIM_TEMPS")

print(f"  FAIT_MESURE_OLT charge  : {df.shape[0]} lignes x {df.shape[1]} colonnes")
print(f"  DIM_EQUIPEMENT          : {dim_equip.shape[0]} enregistrements")
print(f"  DIM_GEOGRAPHIE          : {dim_geo.shape[0]} enregistrements")
print(f"  DIM_TEMPS               : {dim_temps.shape[0]} enregistrements")

# Forcer la conversion numerique des colonnes de mesures
# (certaines cellules Excel peuvent contenir du texte parasite)
for col in FEATURES:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

nb_initial = len(df)

# ─────────────────────────────────────────────────────────────
# ETAPE 1 : CATEGORISATION DES LIGNES
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 1 — Categorisation des lignes")
print(SEP)

def categoriser_ligne(row):
    """
    Meme logique que le notebook de detection :
      - INACTIF         : port desactive (ADMIN=0) ou ligne HS (OPER=0)
      - DONNEE_MANQUANTE: ligne active mais mesures absentes (anomalie de collecte)
      - ACTIF           : ligne active avec toutes les mesures
    """
    mesures_nulles = pd.isna(row[FEATURES]).any()
    if row['admin_status'] == 0 or row['oper_status'] == 0:
        return 'INACTIF'
    elif mesures_nulles:
        return 'DONNEE_MANQUANTE'
    else:
        return 'ACTIF'

df['statut_ligne'] = df.apply(categoriser_ligne, axis=1)

counts = df['statut_ligne'].value_counts()
for statut, n in counts.items():
    pct = 100 * n / len(df)
    print(f"  {statut:<20} : {n:>5} lignes ({pct:.1f}%)")

# ─────────────────────────────────────────────────────────────
# ETAPE 2 : MARQUAGE DES OUTLIERS PHYSIQUES (Methode IQR)
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 2 — Marquage des outliers physiques (IQR)")
print(SEP)

# Plages physiques XPON connues
PHYSICAL_LIMITS = {
    'olt_power_tx':     (0.5,  5.0),
    'olt_rx_ont_power': (-30.0, -8.0),
    'onu_power_tx':     (0.5,  5.0),
    'onu_power_rx':     (-30.0, -8.0),
}

# On ne calcule les outliers que sur les lignes ACTIVES avec mesures
df_actif = df[df['statut_ligne'] == 'ACTIF'].copy()

df['is_outlier'] = 0

for col in FEATURES:
    Q1 = df_actif[col].quantile(0.25)
    Q3 = df_actif[col].quantile(0.75)
    IQR = Q3 - Q1
    lower_iqr = Q1 - 3 * IQR
    upper_iqr = Q3 + 3 * IQR

    # Combinaison IQR + limites physiques pour plus de robustesse
    phys_min, phys_max = PHYSICAL_LIMITS[col]
    lower = max(lower_iqr, phys_min)
    upper = min(upper_iqr, phys_max)

    outlier_mask = (
        df['statut_ligne'] == 'ACTIF'
    ) & (
        (df[col] < lower) | (df[col] > upper)
    )

    df.loc[outlier_mask, 'is_outlier'] = 1
    df[f'{col}_outlier'] = outlier_mask.astype(int)

    nb_out = outlier_mask.sum()
    print(f"  {col:<22} : {nb_out:>4} outliers  [min={lower:.2f}, max={upper:.2f}]")

total_outliers = df['is_outlier'].sum()
print(f"\n  Total lignes avec outlier : {total_outliers} ({100*total_outliers/len(df):.1f}%)")
print("  -> Lignes MARQUEES (non supprimees) : conservees pour l'analyse ML")

# ─────────────────────────────────────────────────────────────
# ETAPE 3 : CORRECTION DE LA DIVERGENCE GEOGRAPHIQUE
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 3 — Correction divergence geographique")
print(SEP)

# La colonne 'gouvernorat' issue de la jointure CO -> GOUVERNORAT est la reference
# La colonne 'DESGOUV' originale (texte libre) peut avoir des erreurs
if 'DESGOUV' in df.columns:
    divergence = df[
        df['gouvernorat'].notna() &
        (df['DESGOUV'].str.strip().str.upper() != df['gouvernorat'].str.strip().str.upper())
    ]
    if len(divergence) > 0:
        print(f"  [!] {len(divergence)} ligne(s) avec divergence DESGOUV <> gouvernorat (CO):")
        print(divergence[['id_mesure', 'DESGOUV', 'gouvernorat']].to_string(index=False))
        print(f"  -> Correction : 'gouvernorat' (source officielle CO) conservee")
    else:
        print("  [OK] Aucune divergence detectee")

    # Dans tous les cas, supprimer la colonne DESGOUV originale
    # car 'gouvernorat' est la colonne officielle
    df.drop(columns=['DESGOUV'], inplace=True, errors='ignore')
    print("  -> Colonne DESGOUV supprimee (remplacee par 'gouvernorat')")
else:
    print("  [OK] Colonne DESGOUV absente, pas de correction necessaire")

# ─────────────────────────────────────────────────────────────
# ETAPE 4 : DETECTION ET SUPPRESSION DES DOUBLONS
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 4 — Detection des doublons")
print(SEP)

nb_avant = len(df)
doublons = df[df.duplicated(subset=['id_mesure'], keep=False)]

if len(doublons) > 0:
    print(f"  [!] {len(doublons)} doublons detectes sur 'id_mesure' :")
    print(doublons[['id_mesure', 'id_carte_olt', 'onu_id']].head(5).to_string(index=False))
    df = df.drop_duplicates(subset=['id_mesure'], keep='first')
    print(f"  -> {nb_avant - len(df)} doublons supprimes")
else:
    print(f"  [OK] Aucun doublon sur 'id_mesure'")

# ─────────────────────────────────────────────────────────────
# ETAPE 5 : VALIDATION FINALE
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 5 — Validation finale")
print(SEP)

checks = {
    "Aucune valeur nulle sur id_mesure"      : df['id_mesure'].isna().sum() == 0,
    "Aucune valeur nulle sur id_carte_olt"   : df['id_carte_olt'].isna().sum() == 0,
    "Aucune valeur nulle sur id_geo"         : df['id_geo'].isna().sum() == 0,
    "Colonne statut_ligne complete"          : df['statut_ligne'].isna().sum() == 0,
    "Aucun doublon sur id_mesure"            : not df.duplicated(subset=['id_mesure']).any(),
    "Colonne is_outlier presente"            : 'is_outlier' in df.columns,
}

all_ok = True
for label, passed in checks.items():
    status = "[OK]" if passed else "[ECHEC]"
    if not passed:
        all_ok = False
    print(f"  {status}  {label}")

# ─────────────────────────────────────────────────────────────
# RAPPORT DE QUALITE FINAL
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  RAPPORT DE QUALITE FINAL")
print(SEP)

total = len(df)
actif          = (df['statut_ligne'] == 'ACTIF').sum()
inactif        = (df['statut_ligne'] == 'INACTIF').sum()
data_manquante = (df['statut_ligne'] == 'DONNEE_MANQUANTE').sum()
outliers_total = df['is_outlier'].sum()
incoherences   = (df.get('nb_incoherences', pd.Series(dtype=int)) >= 1).sum()

print(f"  Lignes initiales              : {nb_initial}")
print(f"  Lignes apres nettoyage        : {total}")
print(f"  Lignes ACTIVES (analysables)  : {actif} ({100*actif/total:.1f}%)")
print(f"  Lignes INACTIVES              : {inactif} ({100*inactif/total:.1f}%)")
print(f"  Lignes DONNEE_MANQUANTE       : {data_manquante} ({100*data_manquante/total:.1f}%)")
print(f"  Lignes avec outlier physique  : {outliers_total} ({100*outliers_total/total:.1f}%)")
print(f"  Lignes avec incoherence flag  : {incoherences} ({100*incoherences/total:.1f}%)")

print(f"\n  Distribution par Gouvernorat :")
print(df['gouvernorat'].value_counts().to_string())

print(f"\n  Distribution par Marque OLT :")
if 'marque' in df.columns:
    print(df['marque'].value_counts().to_string())

# ─────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  EXPORT vers {OUTPUT_FILE}")
print(SEP)

with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    df.to_excel(writer,       sheet_name="FAIT_MESURE_OLT", index=False)
    dim_equip.to_excel(writer, sheet_name="DIM_EQUIPEMENT",  index=False)
    dim_geo.to_excel(writer,   sheet_name="DIM_GEOGRAPHIE",  index=False)
    dim_temps.to_excel(writer, sheet_name="DIM_TEMPS",       index=False)

for sheet in ["FAIT_MESURE_OLT", "DIM_EQUIPEMENT", "DIM_GEOGRAPHIE", "DIM_TEMPS"]:
    print(f"  Feuille [{sheet}] exportee")

print(f"\n  Fichier pret : {OUTPUT_FILE}")
print(f"  Statut global : {'[OK] PRET POUR POSTGRESQL' if all_ok else '[!] VERIFIER LES ECHECS CI-DESSUS'}")
print(f"\n  Prochaine etape -> Conception schema SQL (schema.sql)")
