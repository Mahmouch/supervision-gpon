"""
clean_flat_dataset.py
=====================
Nettoyage du dataset plat flat_dataset_xpon.xlsx :
  1. Suppression des lignes avec mesures de puissance vides
  2. Suppression des doublons
  3. Rapport avant/apres

Entree  : flat_dataset_xpon.xlsx
Sortie  : flat_dataset_xpon_clean.xlsx
"""

import pandas as pd

INPUT  = "flat_dataset_xpon.xlsx"
OUTPUT = "flat_dataset_xpon_clean.xlsx"

MESURES = ["OLT_POWER_TX", "OLT_RX_ONT_POWER", "ONU_POWER_TX", "ONU_POWER_RX"]

SEP = "=" * 55

# ─────────────────────────────────────────────────────────────
# CHARGEMENT
# ─────────────────────────────────────────────────────────────
print(SEP)
print("  Chargement de flat_dataset_xpon.xlsx")
print(SEP)

df = pd.read_excel(INPUT, sheet_name="FAIT_XPON_QUALIF")
nb_initial = len(df)
print(f"  Lignes chargees   : {nb_initial}")
print(f"  Colonnes          : {len(df.columns)}")

# ─────────────────────────────────────────────────────────────
# ETAPE 1 : SUPPRESSION DES LIGNES SANS MESURES DE PUISSANCE
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 1 — Suppression des lignes sans mesures")
print(SEP)

# Une ligne est supprimee si AU MOINS UNE des 4 mesures est vide
masque_vide = df[MESURES].isna().any(axis=1)
nb_vides = masque_vide.sum()

print(f"  Lignes avec au moins 1 mesure vide : {nb_vides}")
print(f"  Detail par colonne :")
for col in MESURES:
    n = df[col].isna().sum()
    print(f"    {col:<22} : {n} valeurs vides")

df = df[~masque_vide].copy()
print(f"\n  -> {nb_vides} lignes supprimees")
print(f"  -> Lignes restantes : {len(df)}")

# ─────────────────────────────────────────────────────────────
# ETAPE 2 : SUPPRESSION DES DOUBLONS
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ETAPE 2 — Suppression des doublons")
print(SEP)

nb_avant_dedup = len(df)
nb_doublons = df.duplicated(subset=["ID_LIGNE"]).sum()

if nb_doublons > 0:
    print(f"  Doublons detectes sur ID_LIGNE : {nb_doublons}")
    df = df.drop_duplicates(subset=["ID_LIGNE"], keep="first")
    print(f"  -> {nb_doublons} doublons supprimes")
else:
    print(f"  [OK] Aucun doublon detecte sur ID_LIGNE")

print(f"  -> Lignes restantes : {len(df)}")

# ─────────────────────────────────────────────────────────────
# RAPPORT FINAL
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  RAPPORT AVANT / APRES NETTOYAGE")
print(SEP)

nb_final    = len(df)
nb_supprime = nb_initial - nb_final

print(f"  Avant nettoyage  : {nb_initial:>6} lignes")
print(f"  Apres nettoyage  : {nb_final:>6} lignes")
print(f"  Lignes supprimees: {nb_supprime:>6} ({100*nb_supprime/nb_initial:.1f}%)")
print(f"  Colonnes         : {len(df.columns)}")

print(f"\n  Qualite du signal apres nettoyage :")
print(df["QUALITE_SIGNAL"].value_counts(dropna=False).to_string())

print(f"\n  Distribution Gouvernorat :")
print(df["GOUVERNORAT"].value_counts().to_string())

print(f"\n  Distribution Marque :")
print(df["MARQUE"].value_counts().to_string())

# ─────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
df.to_excel(OUTPUT, index=False, sheet_name="FAIT_XPON_QUALIF")
print(f"  [OK] Fichier exporte : {OUTPUT}")
print(f"  [OK] {nb_final} lignes x {len(df.columns)} colonnes — 1 seule feuille")
print(f"\n  Prochaine etape -> Creation de la base PostgreSQL")
