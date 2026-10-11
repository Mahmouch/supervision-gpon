# 🌐 Supervision Réseau GPON — Plateforme Intelligente

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-316192?style=for-the-badge&logo=postgresql)
![Scikit-Learn](https://img.shields.io/badge/Scikit--Learn-1.5-F7931E?style=for-the-badge&logo=scikit-learn)

**Plateforme de supervision intelligente des équipements réseau GPON (FTTH)**  
*Projet de Fin d'Études — Mahmoud Chaari*

</div>

---

## 📋 Description

Cette plateforme permet la **supervision, l'analyse OLAP et la détection automatique d'anomalies** sur un réseau GPON (Gigabit Passive Optical Network) en production. Elle combine :

- 🔍 **Détection d'anomalies** par Machine Learning (Isolation Forest + Z-Score)
- 📊 **Analyse OLAP** multidimensionnelle des incidents réseau
- 🤖 **Clustering** des équipements défaillants (K-Means)
- 🚨 **Gestion des réclamations** et tickets d'incidents
- 🔐 **Authentification sécurisée** (JWT + rôles admin/user)

---

## 🛠️ Stack Technologique

| Couche | Technologies |
|--------|-------------|
| **Backend** | FastAPI, Python 3.10+, Uvicorn |
| **Base de données** | PostgreSQL 16, SQLAlchemy, pg8000 |
| **Machine Learning** | Scikit-Learn, NumPy, Pandas, Joblib |
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) |
| **Sécurité** | JWT (python-jose), bcrypt (passlib) |
| **Notebooks** | Jupyter Notebook |

---

## 📁 Structure du Projet

```
supervision-gpon/
├── site_web/
│   ├── backend/
│   │   ├── main.py                    # API FastAPI principale (1760+ lignes)
│   │   ├── check_cols.py              # Vérification colonnes DB
│   │   ├── force_sync_clusters.py     # Synchronisation clusters
│   │   ├── redistribute_temps.py      # Redistribution temporelle
│   │   ├── update_admin.py            # Mise à jour admin
│   │   └── .env.example               # Template variables d'environnement
│   └── frontend/
│       ├── index.html                 # Dashboard principal
│       ├── login.html                 # Page d'authentification
│       ├── anomalies.html             # Vue anomalies détectées
│       ├── analytique.html            # Analyse OLAP
│       ├── equipements.html           # Gestion équipements
│       ├── reclamations.html          # Gestion réclamations
│       ├── prediction.html            # Prédiction ML
│       ├── admin.html                 # Interface administrateur
│       ├── auth.js                    # Logique authentification
│       ├── nav.js                     # Navigation
│       └── style_shared.css           # Styles communs
├── fichier_python/
│   ├── db_setup.py                    # Initialisation base de données
│   ├── create_users.py                # Création utilisateurs
│   ├── create_views.py                # Création vues SQL
│   └── inject_ml.py                   # Injection résultats ML en DB
├── services/
│   └── predictor.py                   # Service de prédiction ML
├── models/
│   ├── isolation_forest.pkl           # Modèle détection anomalies
│   ├── cluster_model.pkl              # Modèle clustering
│   ├── scaler.pkl                     # Normalisation features
│   ├── metadata.pkl                   # Métadonnées modèles
│   └── ...                            # Autres artefacts ML
├── nettoyage/
│   ├── clean_dataset.py               # Nettoyage données brutes
│   ├── clean_flat_dataset.py          # Flatten & nettoyage
│   └── *.ipynb                        # Notebooks de nettoyage
├── notebooks/                         # Notebooks ML & analyse
│   ├── anomaly_detection_unsupervised.ipynb
│   ├── clustering_anomalies.ipynb
│   ├── detection_anomalies.ipynb
│   ├── machine_learning_complet.ipynb
│   └── ...
├── .gitignore
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🚀 Installation & Lancement

### Prérequis
- Python 3.10+
- PostgreSQL 16
- pip

### 1. Cloner le dépôt
```bash
git clone https://github.com/<votre-username>/supervision-gpon.git
cd supervision-gpon
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Configurer les variables d'environnement
```bash
# Copier le template
cp .env.example site_web/backend/.env

# Éditer avec vos valeurs
# DATABASE_URL=postgresql+pg8000://postgres:YOUR_PASSWORD@localhost:5432/supervision_gpon
# AUTH_SECRET=your-secret-key
```

### 4. Initialiser la base de données
```bash
python fichier_python/db_setup.py
python fichier_python/create_users.py
python fichier_python/create_views.py
```

### 5. Injecter les résultats ML
```bash
python fichier_python/inject_ml.py
```

### 6. Lancer le serveur
```bash
cd site_web/backend
uvicorn main:app --reload --port 8000
```

L'application sera disponible sur : **http://localhost:8000**

---

## 🤖 Modèles Machine Learning

| Modèle | Algorithme | Rôle |
|--------|-----------|------|
| `isolation_forest.pkl` | Isolation Forest | Détection anomalies non-supervisée |
| `cluster_model.pkl` | K-Means | Regroupement équipements défaillants |
| `scaler.pkl` | StandardScaler | Normalisation des features |
| `zscore_threshold.pkl` | Z-Score | Seuil de détection statistique |

---

## 📡 API Endpoints Principaux

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/auth/login` | Authentification |
| `GET` | `/api/equipements` | Liste équipements GPON |
| `GET` | `/api/anomalies` | Anomalies détectées |
| `GET` | `/api/reclamations` | Gestion réclamations |
| `POST` | `/api/predict` | Prédiction ML |
| `GET` | `/api/analytique/...` | Analyses OLAP |

Documentation interactive disponible sur : **http://localhost:8000/docs**

---

## 🔐 Sécurité

- Authentification par **JWT** (JSON Web Token)
- Mots de passe hashés avec **pbkdf2_sha256**
- Variables sensibles dans `.env` (jamais dans le code)
- Rôles différenciés : `admin` / `user`

---

## 👤 Auteur

**Mahmoud Chaari**  
Projet de Fin d'Études — Supervision Intelligente Réseau GPON  

---

## 📄 Licence

Ce projet est réalisé dans le cadre d'un projet académique (PFE).
