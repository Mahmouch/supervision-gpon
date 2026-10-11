"""
================================================
  SUPERVISION RESEAU GPON — Backend FastAPI
  Fichier : main.py
  Lancement : uvicorn main:app --reload --port 8000
================================================
"""

from fastapi import FastAPI, HTTPException, Query, Depends, UploadFile, File
from dotenv import load_dotenv

# Chargement des variables d'environnement depuis .env
load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from contextlib import asynccontextmanager
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from jose import JWTError, jwt
from passlib.context import CryptContext
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import os
import uuid

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
# Chargé depuis .env — voir .env.example pour le template
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+pg8000://postgres:password@localhost:5432/supervision_gpon"
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "..", "..", "models")  # ../../models/

# Authentification JWT — définir AUTH_SECRET dans .env en production
SECRET_KEY = os.environ.get("AUTH_SECRET", "dev-supervision-gpon-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ─────────────────────────────────────────────
# STOCKAGE GLOBAL DES MODELES & REFERENTIELS
# ─────────────────────────────────────────────
models = {}
engine = None

# Ces dictionnaires seront peuplés dynamiquement au chargement des modèles
CLUSTER_NAMES = {}
CLUSTER_DESCRIPTIONS = {}


def init_app_users() -> None:
    """Crée la table des comptes applicatifs et insère des comptes de démonstration si besoin."""
    if engine is None:
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_user (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                username VARCHAR(255) UNIQUE NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'technicien')),
                assigned_gouvernorat VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        n = conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar() or 0
        if int(n) == 0:
            conn.execute(text("""
                INSERT INTO app_user (email, username, hashed_password, role, assigned_gouvernorat)
                VALUES
                    (:e1, 'admin', :p1, 'admin', NULL),
                    (:e2, 'technicien', :p2, 'technicien', 'SFAX')
            """), {
                "e1": "admin@gpon.local",
                "p1": pwd_context.hash("Admin123!"),
                "e2": "tech@gpon.local",
                "p2": pwd_context.hash("Tech123!"),
            })
            print("Comptes demo : admin@gpon.local / Admin123!  |  tech@gpon.local / Tech123!")

        # Table des réclamations
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reclamation (
                id SERIAL PRIMARY KEY,
                onu_id VARCHAR(100) NOT NULL,
                gouvernorat VARCHAR(100) NOT NULL,
                technicien VARCHAR(255) NOT NULL,
                type_probleme VARCHAR(255) NOT NULL,
                description TEXT,
                statut VARCHAR(50) DEFAULT 'EN_ATTENTE',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        
        # Mise à jour du schéma existant (si la table existait déjà)
        conn.execute(text("ALTER TABLE reclamation ADD COLUMN IF NOT EXISTS id_port VARCHAR(50);"))
        conn.execute(text("ALTER TABLE reclamation ADD COLUMN IF NOT EXISTS id_carte VARCHAR(50);"))
        
        # S'assurer que le statut accepte NON_RESOLU. Pour simplifier, on enlève le CHECK ou on le remplace.
        conn.execute(text("ALTER TABLE reclamation DROP CONSTRAINT IF EXISTS reclamation_statut_check;"))
        conn.execute(text("ALTER TABLE reclamation ADD CONSTRAINT reclamation_statut_check CHECK (statut IN ('EN_ATTENTE', 'EN_COURS', 'RESOLU', 'NON_RESOLU'));"))


def get_user_row(identifier: str) -> Optional[Dict[str, Any]]:
    if engine is None:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, email, username, hashed_password, role, assigned_gouvernorat
                FROM app_user
                WHERE LOWER(username) = LOWER(:id) OR LOWER(email) = LOWER(:id)
                LIMIT 1
            """),
            {"id": identifier.strip()},
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "hashed_password": row[3],
        "role": row[4],
        "assigned_gouvernorat": row[5],
    }


def authenticate_user(identifier: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_row(identifier)
    if not user or not pwd_context.verify(password, user["hashed_password"]):
        return None
    return user


def create_access_token(subject: str, extra: Dict[str, Any]) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, **extra}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    cred = HTTPException(
        status_code=401,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: Optional[str] = payload.get("sub")
        if not sub:
            raise cred
    except JWTError:
        raise cred
    user = get_user_row(sub)
    if not user:
        raise cred
    return user


def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    return user


def effective_gouvernorat_filter(user: Dict[str, Any], query_param: Optional[str]) -> Optional[str]:
    """Technicien avec zone assignée : la zone prime sur le paramètre d'URL."""
    if user.get("role") == "technicien" and user.get("assigned_gouvernorat"):
        return user["assigned_gouvernorat"]
    return query_param


# ─────────────────────────────────────────────
# DEMARRAGE / ARRET
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine

    # Connexion PostgreSQL
    engine = create_engine(DB_URL, pool_size=5, max_overflow=10)

    try:
        init_app_users()
    except Exception as e:
        print(f"Avertissement init app_user : {e}")

    # Charger les modeles ML
    try:
        # 1. Chargement du modèle de clustering consolidé
        cluster_data = joblib.load(os.path.join(MODELS_DIR, "cluster_model.pkl"))
        models["cluster"] = cluster_data["kmeans"]
        models["scaler_kmeans"] = cluster_data["scaler"]
        
        # On récupère le mapping dynamique pour le site web
        global CLUSTER_NAMES, CLUSTER_DESCRIPTIONS
        CLUSTER_NAMES = cluster_data["mapping"]
        
        # Génération automatique des descriptions selon le nom
        desc_map = {
            'port': "Anomalie de type PORT — Regroupement massif d'erreurs sur un port OLT spécifique.",
            'carte': "Anomalie de type CARTE — Panne groupée affectant plusieurs ports d'une même carte.",
            'admin': "Anomalie ADMINISTRATIVE — Suspension ou erreur de configuration détectée.",
            'autre': "Anomalie ISOLÉE — Incident ne présentant pas de caractère groupé (Client individuel)."
        }
        CLUSTER_DESCRIPTIONS = {cid: desc_map.get(name.lower(), "Anomalie classée") 
                              for cid, name in CLUSTER_NAMES.items()}
        
        # 2. Chargement du modèle d'anomalie (Isolation Forest)
        if os.path.exists(os.path.join(MODELS_DIR, "isolation_forest.pkl")):
            models["anomaly"] = joblib.load(os.path.join(MODELS_DIR, "isolation_forest.pkl"))
        
        # 3. Chargement des métadonnées Z-Score
        if os.path.exists(os.path.join(MODELS_DIR, "anomaly_model.pkl")):
            models["zscore_meta"] = joblib.load(os.path.join(MODELS_DIR, "anomaly_model.pkl"))
        
        models["scaler"] = joblib.load(os.path.join(MODELS_DIR, "scaler.pkl"))
        
        print(f"Modeles ML charges : {len(models)} fichiers, {len(CLUSTER_NAMES)} clusters dynamiques.")
    except Exception as e:
        print(f"Erreur lors du chargement des modeles ML : {e}")
        print("Les endpoints /predict pourraient ne pas fonctionner.")

    print("Backend GPON demarre sur http://localhost:8000")
    print("Documentation API : http://localhost:8000/docs")
    yield

    models.clear()
    if engine:
        engine.dispose()

# ─────────────────────────────────────────────
# APPLICATION FASTAPI
# ─────────────────────────────────────────────
app = FastAPI(
    lifespan=lifespan,
    title="Supervision Reseau GPON",
    description="API analytique pour la detection d'anomalies reseau fibre optique",
    version="1.0.0"
)

# CORS — obligatoire pour que le frontend HTML puisse appeler l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production : mettre l'URL exacte du frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

# Les routes statiques seront ajoutées à la fin du fichier pour éviter les conflits avec les APIs.

# ─────────────────────────────────────────────
# SCHEMAS PYDANTIC
# ─────────────────────────────────────────────
class MesureOLT(BaseModel):
    olt_power_tx: float
    olt_rx_ont_power: float
    onu_power_tx: float
    onu_power_rx: float
    f_susp: int = 0
    admin_status: int = 1
    oper_status: int = 1
    gouvernorat: str = None
    host_name: str = None

class PredictionResult(BaseModel):
    anomalie: bool
    score: float
    cluster: int
    cluster_nom: str
    cluster_description: str
    type_anomalie: str
    severite: str
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    assigned_gouvernorat: Optional[str] = Field(
        default=None,
        description="Gouvernorat d'affectation (optionnel) — limite les stats pour ce technicien",
    )

class ReclamationSchema(BaseModel):
    onu_id: str
    type_probleme: str
    description: str
    gouvernorat: str
    technicien: str
    id_port: Optional[str] = None
    id_carte: Optional[str] = None

class ReclamationStatusUpdate(BaseModel):
    statut: str


class UserMe(BaseModel):
    id: int
    email: str
    username: str
    role: str
    assigned_gouvernorat: Optional[str] = None

# ─────────────────────────────────────────────
# ROUTE RACINE
# ─────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "message": "Supervision Reseau GPON — API operationnelle",
        "version": "1.0.0",
        "endpoints": [
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/me",
            "/api/stats/global",
            "/api/stats/gouvernorats",
            "/api/stats/reclamations-par-centrale",
            "/api/stats/marques",
            "/api/anomalies",
            "/api/predict",
            "/api/incidents",
            "/api/clusters",
            "/health"
        ]
    }

@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "OK", "database": "connectee", "models": list(models.keys())}
    except Exception as e:
        return {"status": "ERROR", "detail": str(e)}


# ─────────────────────────────────────────────
# AUTHENTIFICATION
# ─────────────────────────────────────────────
@app.post("/api/auth/login", response_model=TokenResponse)
def auth_login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect")
    token = create_access_token(
        subject=user["username"],
        extra={"role": user["role"], "email": user["email"]},
    )
    return TokenResponse(access_token=token)


@app.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    if engine is None:
        raise HTTPException(status_code=500, detail="Base de données non connectée")
    
    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM app_user WHERE email = :e OR username = :u"),
                {"e": req.email, "u": req.username}
            ).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="Email ou nom d'utilisateur déjà utilisé")

            conn.execute(
                text("""
                    INSERT INTO app_user (email, username, hashed_password, role, assigned_gouvernorat)
                    VALUES (:email, :username, :password, 'technicien', :gouv)
                """),
                {
                    "email": req.email,
                    "username": req.username,
                    "password": pwd_context.hash(req.password),
                    "gouv": req.assigned_gouvernorat
                }
            )
        return {"message": "Utilisateur créé avec succès"}
    except Exception:
        raise HTTPException(status_code=400, detail="Erreur lors de l'inscription")


@app.get("/api/auth/me", response_model=UserMe)
def auth_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return UserMe(
        id=current_user["id"],
        email=current_user["email"],
        username=current_user["username"],
        role=current_user["role"],
        assigned_gouvernorat=current_user["assigned_gouvernorat"],
    )


# ─────────────────────────────────────────────
# GESTION DES RECLAMATIONS
# ─────────────────────────────────────────────
@app.get("/api/reclamations")
def get_reclamations(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Lister les réclamations. Les techniciens ne voient que leur gouvernorat."""
    with engine.connect() as conn:
        query = "SELECT id, onu_id, gouvernorat, technicien, type_probleme, description, statut, created_at, id_port, id_carte FROM reclamation"
        params = {}
        
        if current_user["role"] == "technicien" and current_user["assigned_gouvernorat"]:
            query += " WHERE gouvernorat = :gouv"
            params["gouv"] = current_user["assigned_gouvernorat"]
        
        query += " ORDER BY created_at DESC"
        rows = conn.execute(text(query), params).fetchall()
        
    return [
        {
            "id": r[0], "onu_id": r[1], "gouvernorat": r[2], "technicien": r[3],
            "type_probleme": r[4], "description": r[5], "statut": r[6], "created_at": r[7],
            "id_port": r[8], "id_carte": r[9]
        }
        for r in rows
    ]


@app.post("/api/reclamations")
def create_reclamation(req: ReclamationSchema, admin_user: Dict[str, Any] = Depends(require_admin)):
    """Créer une réclamation (Admin uniquement)."""
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO reclamation (onu_id, gouvernorat, technicien, type_probleme, description, id_port, id_carte)
                VALUES (:onu, :gouv, :tech, :type, :desc, :port, :carte)
            """),
            {
                "onu": req.onu_id,
                "gouv": req.gouvernorat,
                "tech": req.technicien,
                "type": req.type_probleme,
                "desc": req.description,
                "port": req.id_port,
                "carte": req.id_carte
            }
        )
    return {"message": "Réclamation créée"}


@app.patch("/api/reclamations/{id}/status")
def update_reclamation_status(id: int, req: ReclamationStatusUpdate, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Mettre à jour le statut d'une réclamation (Admin et Technicien)."""
    # Validation du statut
    allowed_statuses = {'EN_ATTENTE', 'EN_COURS', 'RESOLU', 'NON_RESOLU'}
    statut_upper = req.statut.upper().strip()
    if statut_upper not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Statut invalide. Choisir parmi {allowed_statuses}")
        
    with engine.begin() as conn:
        if current_user["role"] == "technicien":
            # On vérifie si la réclamation appartient au gouvernorat du technicien
            rec = conn.execute(
                text("SELECT gouvernorat FROM reclamation WHERE id = :id"),
                {"id": id}
            ).fetchone()
            if not rec:
                raise HTTPException(status_code=404, detail="Réclamation non trouvée")
            if current_user["assigned_gouvernorat"] and rec[0] != current_user["assigned_gouvernorat"]:
                raise HTTPException(status_code=403, detail="Vous n'êtes pas autorisé à modifier une réclamation d'un autre gouvernorat")

        conn.execute(
            text("UPDATE reclamation SET statut = :statut WHERE id = :id"),
            {"statut": statut_upper, "id": id}
        )
    return {"message": "Statut mis à jour"}


# ─────────────────────────────────────────────
# ATTRIBUTION AUTOMATIQUE ET RECOMMANDATION
# ─────────────────────────────────────────────
class AutoAssignRequest(BaseModel):
    onu_id: str

@app.get("/api/admin/anomaly-details/{onu_id}")
def get_anomaly_details(onu_id: str, admin_user: Dict[str, Any] = Depends(require_admin)):
    """Récupère les détails d'une anomalie et recommande le technicien le moins chargé."""
    with engine.connect() as conn:
        # 1. Rechercher l'anomalie
        anom = conn.execute(
            text("""
                SELECT 
                    f.onu_id, g.gouvernorat, f.id_carte_olt, f.no_port, 
                    f.olt_rx_ont_power, f.onu_power_tx, f.ml_cluster, f.ml_type_anomalie,
                    ch.marque
                FROM fait_mesure_olt f
                JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
                LEFT JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
                JOIN dim_temps t ON f.id_temps = t.id_temps
                WHERE f.onu_id = :onu_id
                ORDER BY t.date_mesure DESC
                LIMIT 1
            """),
            {"onu_id": onu_id}
        ).fetchone()

        if not anom:
            raise HTTPException(status_code=404, detail="Détails de l'ONU non trouvés")

        gouvernorat = anom[1]
        id_carte = str(anom[2]) if anom[2] is not None else ""
        id_port = str(anom[3]) if anom[3] is not None else ""
        olt_rx = float(anom[4]) if anom[4] is not None else 0.0
        onu_tx = float(anom[5]) if anom[5] is not None else 0.0
        cluster = anom[6]
        type_anom_db = anom[7]
        marque = anom[8] or "Inconnue"

        # Formater type_probleme et description suggérée
        cat = get_category_from_cluster(cluster, type_anom_db)
        type_probleme = type_anom_db if type_anom_db else f"Anomalie de type {cat}"
        
        description = (
            f"Anomalie détectée automatiquement par le pipeline ML.\n"
            f"Equipement OLT: Marque {marque} | Carte {id_carte} | Port {id_port}.\n"
            f"Mesures physiques: OLT RX Power: {olt_rx:.2f} dBm, ONU TX Power: {onu_tx:.2f} dBm.\n"
            f"Catégorie de panne: {cat} (Cluster {cluster})."
        )

        # 2. Trouver tous les techniciens affectés à ce gouvernorat
        techs = conn.execute(
            text("""
                SELECT username FROM app_user 
                WHERE role = 'technicien' AND assigned_gouvernorat = :gouv
                ORDER BY username
            """),
            {"gouv": gouvernorat}
        ).fetchall()

        tech_list = []
        recommended_tech = None
        min_tasks = 999999

        for r_tech in techs:
            tech_name = r_tech[0]
            # Compter les tâches actives de ce technicien
            active_count = conn.execute(
                text("""
                    SELECT COUNT(*) FROM reclamation 
                    WHERE technicien = :tech AND statut IN ('EN_ATTENTE', 'EN_COURS')
                """),
                {"tech": tech_name}
            ).scalar() or 0

            tech_list.append({
                "username": tech_name,
                "active_tasks": active_count
            })

            if active_count < min_tasks:
                min_tasks = active_count
                recommended_tech = tech_name

        # Si aucun technicien n'est affecté à ce gouvernorat, suggérer de l'affecter à n'importe quel technicien
        if not recommended_tech:
            # Récupérer n'importe quel technicien
            all_techs = conn.execute(
                text("SELECT username, assigned_gouvernorat FROM app_user WHERE role = 'technicien' ORDER BY username")
            ).fetchall()
            for r_tech in all_techs:
                tech_name = r_tech[0]
                tech_gouv = r_tech[1] or "SFAX"
                active_count = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM reclamation 
                        WHERE technicien = :tech AND statut IN ('EN_ATTENTE', 'EN_COURS')
                    """),
                    {"tech": tech_name}
                ).scalar() or 0
                tech_list.append({
                    "username": tech_name,
                    "active_tasks": active_count,
                    "gouvernorat": tech_gouv
                })
                if active_count < min_tasks:
                    min_tasks = active_count
                    recommended_tech = tech_name

        return {
            "onu_id": onu_id,
            "gouvernorat": gouvernorat,
            "id_port": id_port,
            "id_carte": id_carte,
            "type_probleme": type_probleme,
            "description": description,
            "recommended_technicien": recommended_tech,
            "technicians": tech_list
        }

@app.post("/api/reclamations/auto-assign")
def auto_assign_reclamation(req: AutoAssignRequest, admin_user: Dict[str, Any] = Depends(require_admin)):
    """Attribution automatique d'une réclamation en 1-Clic."""
    try:
        details = get_anomaly_details(req.onu_id, admin_user)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des détails : {str(e)}")

    recommended_tech = details["recommended_technicien"]
    if not recommended_tech:
        raise HTTPException(status_code=400, detail="Aucun technicien disponible pour l'attribution automatique.")

    # Créer la réclamation
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO reclamation (onu_id, gouvernorat, technicien, type_probleme, description, id_port, id_carte, statut)
                VALUES (:onu, :gouv, :tech, :type, :desc, :port, :carte, 'EN_ATTENTE')
            """),
            {
                "onu": details["onu_id"],
                "gouv": details["gouvernorat"],
                "tech": recommended_tech,
                "type": details["type_probleme"],
                "desc": details["description"],
                "port": details["id_port"],
                "carte": details["id_carte"]
            }
        )

    return {
        "success": True,
        "message": f"Réclamation pour l'ONU {req.onu_id} créée et attribuée automatiquement à {recommended_tech} ({details['gouvernorat']}).",
        "technicien": recommended_tech,
        "gouvernorat": details["gouvernorat"]
    }




# ─────────────────────────────────────────────
# STATS GLOBALES
# ─────────────────────────────────────────────
@app.get("/api/stats/global")
async def stats_global(gouvernorat: Optional[str] = None, category: Optional[str] = None, user: Dict[str, Any] = Depends(get_current_user)):
    """KPIs principaux pour les cartes du dashboard."""
    eff_gouv = effective_gouvernorat_filter(user, gouvernorat)
    params = {}
    filters = ["f.ml_anomalie_pred IS NOT NULL"]

    if eff_gouv:
        filters.append("g.gouvernorat = :g")
        params["g"] = eff_gouv

    if category:
        cat_map = {"PORT": 0, "AUTRE": 1, "ADMIN": 2, "CARTE": 3}
        if category in cat_map:
            filters.append("f.ml_cluster = :cat")
            params["cat"] = cat_map[category]

    filt_str = " AND ".join(filters)
    query = f"""
        SELECT
            COUNT(*)                                        AS total_mesures,
            SUM(f.ml_anomalie_pred)                         AS nb_anomalies,
            ROUND(AVG(f.ml_anomalie_pred::numeric) * 100, 2) AS taux_anomalie_pct,
            SUM(f.anomalie_technique)                       AS nb_tech,
            SUM(f.anomalie_admin)                           AS nb_admin,
            ROUND(AVG(f.olt_rx_ont_power)::numeric, 2)      AS moy_olt_rx,
            ROUND(AVG(f.ml_anomalie_score)::numeric, 4)     AS score_moyen
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE {filt_str}
    """
    with engine.connect() as conn:
        result = conn.execute(text(query), params).fetchone()

    # Incidents depuis log_incidents (filtrés par gouvernorat)
    with engine.connect() as conn:
        inc_filt = ""
        if eff_gouv:
            inc_filt = " JOIN fait_mesure_olt f ON li.id_ligne = f.id_ligne JOIN dim_gouvernorat g ON f.codgouv = g.codgouv WHERE g.gouvernorat = :g AND "
        else:
            inc_filt = " WHERE "
            
        incidents_query = f"SELECT COUNT(DISTINCT li.id_incident) FROM log_incidents li {inc_filt} li.statut = 'DETECTE'"
        incidents = conn.execute(text(incidents_query), params).scalar()

    return {
        "total_mesures":    int(result[0]),
        "nb_anomalies":     int(result[1]),
        "taux_anomalie":    float(result[2]),
        "nb_tech":          int(result[3] or 0),
        "nb_admin":         int(result[4] or 0),
        "moy_olt_rx":       float(result[5] or 0),
        "score_moyen":      float(result[6] or 0),
        "incidents":        int(incidents or 0)
    }

@app.get("/api/stats/evolution")
def stats_evolution(
    category: Optional[str] = None,
    days: Optional[int] = None,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Evolution temporelle des anomalies groupée par jour."""
    params = {}
    filters = ["f.anomalie IS NOT NULL"]

    eff_gouv = effective_gouvernorat_filter(user, None)
    if eff_gouv:
        filters.append("g.gouvernorat = :gouv")
        params["gouv"] = eff_gouv

    if category:
        cat_map = {"PORT": 0, "AUTRE": 1, "ADMIN": 2, "CARTE": 3}
        if category in cat_map:
            filters.append("f.ml_cluster = :cat")
            params["cat"] = cat_map[category]

    if days:
        filters.append("t.date_seule >= CURRENT_DATE - INTERVAL ':days days'")
        # Use string formatting for interval (pg8000 limitation)
        where_str = " AND ".join(filters).replace(
            "INTERVAL ':days days'", f"INTERVAL '{days} days'"
        )
    else:
        where_str = " AND ".join(filters)

    query = f"""
        SELECT
            t.date_seule,
            COUNT(*)            AS total_mesures,
            SUM(f.anomalie)     AS nb_anomalies,
            ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_pct
        FROM fait_mesure_olt f
        JOIN dim_temps t ON f.id_temps = t.id_temps
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE {where_str}
        GROUP BY t.date_seule
        ORDER BY t.date_seule ASC
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
    return [
        {
            "date":   str(r[0]),
            "total":  int(r[1]),
            "nb":     int(r[2] or 0),
            "taux":   float(r[3] or 0)
        }
        for r in rows
    ]

# ─────────────────────────────────────────────
# STATS PAR GOUVERNORAT
# ─────────────────────────────────────────────
@app.get("/api/stats/gouvernorats")
def stats_gouvernorats(category: Optional[str] = None, user: Dict[str, Any] = Depends(get_current_user)):
    """Taux anomalie par gouvernorat — pour le graphique barres et la carte."""
    params = {}
    filters = ["f.anomalie IS NOT NULL"]

    eff_gouv = effective_gouvernorat_filter(user, None)
    if eff_gouv:
        filters.append("g.gouvernorat = :gouv")
        params["gouv"] = eff_gouv
    
    if category:
        cat_map = {"PORT": 0, "AUTRE": 1, "ADMIN": 2, "CARTE": 3}
        if category in cat_map:
            filters.append("f.ml_cluster = :cat")
            params["cat"] = cat_map[category]

    filt_str = " AND ".join(filters)
    query = f"""
        SELECT
            g.gouvernorat,
            COUNT(*)                                    AS total,
            SUM(f.anomalie)                             AS nb_anomalies,
            ROUND(AVG(f.anomalie::numeric)*100, 2)      AS taux_pct,
            ROUND(AVG(f.olt_rx_ont_power)::numeric, 2) AS moy_olt_rx,
            ROUND(AVG(f.ml_anomalie_score)::numeric, 4) AS score_moyen
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE {filt_str}
        GROUP BY g.gouvernorat
        ORDER BY nb_anomalies DESC
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [
        {
            "gouvernorat":  r[0],
            "total":        int(r[1]),
            "nb_anomalies": int(r[2]),
            "taux_pct":     float(r[3]),
            "moy_olt_rx":   float(r[4] or 0),
            "score_moyen":  float(r[5] or 0)
        }
        for r in rows
    ]

# ─────────────────────────────────────────────
# STATS PAR MARQUE
# ─────────────────────────────────────────────
@app.get("/api/stats/reclamations-par-centrale")
def stats_reclamations_par_centrale(user: Dict[str, Any] = Depends(get_current_user)):
    """Nombre de réclamations (mesures anormales) par gouvernorat et par centrale (ville)."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params: Dict[str, Any] = {}
    if eff_gouv:
        params["gouv"] = eff_gouv
    query = f"""
        SELECT
            g.gouvernorat,
            c.centrale AS ville_centrale,
            COUNT(*) AS total_mesures,
            SUM(f.ml_anomalie_pred) AS nb_reclamations
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        JOIN dim_centrale c ON f.id_co = c.id_co
        WHERE f.ml_anomalie_pred IS NOT NULL {filt}
        GROUP BY g.gouvernorat, c.centrale
        ORDER BY g.gouvernorat, SUM(f.ml_anomalie_pred) DESC
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
    return [
        {
            "gouvernorat": r[0],
            "ville_centrale": r[1],
            "total_mesures": int(r[2]),
            "nb_reclamations": int(r[3] or 0),
        }
        for r in rows
    ]


@app.get("/api/stats/marques")
def stats_marques(user: Dict[str, Any] = Depends(get_current_user)):
    """Anomalies HUAWEI vs ALCATEL."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params = {}
    if eff_gouv: params["gouv"] = eff_gouv

    query = f"""
        SELECT
            c.marque,
            COUNT(*)                                AS total,
            SUM(f.ml_anomalie_pred)                 AS nb_anomalies,
            ROUND(AVG(f.ml_anomalie_pred::numeric)*100, 2)  AS taux_pct
        FROM fait_mesure_olt f
        JOIN dim_olt_chassis c ON f.id_chss_olt = c.id_chss_olt
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE f.ml_anomalie_pred IS NOT NULL {filt}
        GROUP BY c.marque
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    res = {
        "taux_huawei": 0, "total_huawei": 0, "anom_huawei": 0,
        "taux_alcatel": 0, "total_alcatel": 0, "anom_alcatel": 0
    }
    for r in rows:
        m = r[0].upper()
        if "HUAWEI" in m:
            res["taux_huawei"] = float(r[3] or 0); res["total_huawei"] = int(r[1]); res["anom_huawei"] = int(r[2] or 0)
        elif "ALCATEL" in m:
            res["taux_alcatel"] = float(r[3] or 0); res["total_alcatel"] = int(r[1]); res["anom_alcatel"] = int(r[2] or 0)
    return res

@app.get("/api/stats/top_ports")
def stats_top_ports(user: Dict[str, Any] = Depends(get_current_user)):
    """Top 10 des ports les plus critiques."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params = {}
    if eff_gouv: params["gouv"] = eff_gouv

    query = f"""
        SELECT f.id_chss_olt, f.id_carte_olt, f.no_port, COUNT(*) as nb
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE f.anomalie = 1 {filt}
        GROUP BY f.id_chss_olt, f.id_carte_olt, f.no_port
        ORDER BY nb DESC
        LIMIT 10
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
    return [{"label": f"OLT {r[0]} | Carte {r[1]} | Port {r[2]}", "nb": int(r[3])} for r in rows]

def get_category_from_cluster(cluster_id, type_anom=""):
    """Mappe les clusters granulaires vers les 4 catégories demandées."""
    c = str(cluster_id)
    t = str(type_anom).upper()
    if "ADMIN" in t or c == "2": return "ADMIN"
    if "CARTE" in t or c == "3": return "CARTE"
    if "PORT" in t or c == "0":  return "PORT"
    return "AUTRE"

@app.get("/api/stats/clusters")
def stats_clusters(user: Dict[str, Any] = Depends(get_current_user)):
    """Analyse par cluster regroupée en 4 catégories : PORT, ADMIN, CARTE, AUTRE."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params = {}
    if eff_gouv: params["gouv"] = eff_gouv

    query = f"""
        SELECT f.ml_cluster, f.ml_type_anomalie, COUNT(*) 
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE f.anomalie=1 {filt}
        GROUP BY f.ml_cluster, f.ml_type_anomalie
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
    
    stats = {"PORT": 0, "ADMIN": 0, "CARTE": 0, "AUTRE": 0}
    for r in rows:
        cat = get_category_from_cluster(r[0], r[1])
        stats[cat] += int(r[2])
    
    return [{"groupe": k, "nb_anomalies": v} for k, v in stats.items() if v > 0]


# Les versions ROLAP optimisées en bas de page sont utilisées.

# ─────────────────────────────────────────────
# LISTE DES ANOMALIES (avec filtres et pagination)
# ─────────────────────────────────────────────
@app.get("/api/anomalies")
def get_anomalies(
    user: Dict[str, Any] = Depends(get_current_user),
    gouvernorat: str = Query(None, description="Filtrer par gouvernorat"),
    type_anomalie: str = Query(None, description="technique ou admin"),
    centrale: str = Query(None, description="Filtrer par centrale (ville)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Liste des anomalies detectees avec filtres."""
    offset = (page - 1) * limit
    conditions = ["f.anomalie = 1"]
    params = {"limit": limit, "offset": offset}

    gouv_eff = effective_gouvernorat_filter(user, gouvernorat)
    if gouv_eff:
        conditions.append("g.gouvernorat = :gouvernorat")
        params["gouvernorat"] = gouv_eff

    if type_anomalie == "technique":
        conditions.append("f.anomalie_technique = 1")
    elif type_anomalie == "admin":
        conditions.append("f.anomalie_admin = 1")

    if centrale:
        conditions.append("c.centrale = :centrale")
        params["centrale"] = centrale

    where = " AND ".join(conditions)

    query = f"""
        SELECT
            f.id_fait, t.date_mesure, g.gouvernorat, c.centrale, ch.host_name, ch.marque,
            f.olt_rx_ont_power, f.onu_power_tx, f.ml_anomalie_score, f.ml_cluster,
            f.ml_type_anomalie, f.anomalie_technique, f.anomalie_admin, f.onu_id
        FROM fait_mesure_olt f
        JOIN dim_temps t       ON f.id_temps     = t.id_temps
        JOIN dim_gouvernorat g ON f.codgouv      = g.codgouv
        JOIN dim_centrale c    ON f.id_co        = c.id_co
        JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
        WHERE {where}
        ORDER BY t.date_mesure DESC
        LIMIT :limit OFFSET :offset
    """

    count_query = f"""
        SELECT COUNT(*) FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        JOIN dim_centrale c    ON f.id_co   = c.id_co
        WHERE {where}
    """

    with engine.connect() as conn:
        total = conn.execute(text(count_query), params).scalar() or 0
        rows = conn.execute(text(query), params).fetchall()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total // limit) + (1 if total % limit > 0 else 0),
        "data": [
            {
                "id": r[0], "date_mesure": str(r[1]), "gouvernorat": r[2], "centrale": r[3],
                "host_name": r[4], "marque": r[5], "olt_rx_power": float(r[6] or 0),
                "onu_power_tx": float(r[7] or 0), "score": float(r[8] or 0),
                "cluster": r[9], "type_anomalie": r[10],
                "est_technique": bool(r[11]), "est_admin": bool(r[12]),
                "onu_id": r[13],
                "categorie": get_category_from_cluster(r[9], r[10])
            }
            for r in rows
        ]
    }

# ─────────────────────────────────────────────
# PREDICTION (MODELE IA)
# ─────────────────────────────────────────────
@app.post("/api/predict")
def predict_anomalie(mesure: MesureOLT, _user: Dict[str, Any] = Depends(get_current_user)):
    """Inférence réelle par les modèles IA (Isolation Forest + Z-Score + Règles + Clustering KMeans)."""
    print(f"DEBUG: Inférence ML demandée : {mesure}")

    # 1. Règles Métier
    is_anomaly_rule_phys = (mesure.olt_rx_ont_power < -28)
    is_anomaly_rule_admin = (mesure.f_susp > 0 and mesure.admin_status == 1)

    # 2. Inférence Isolation Forest
    is_anomaly_if = False
    if_score = 0.0
    if "anomaly" in models and "scaler" in models:
        try:
            X_in = pd.DataFrame([[
                mesure.olt_power_tx,
                mesure.olt_rx_ont_power,
                mesure.onu_power_tx,
                mesure.onu_power_rx
            ]], columns=["OLT_POWER_TX", "OLT_RX_ONT_POWER", "ONU_POWER_TX", "ONU_POWER_RX"])
            X_scaled = models["scaler"].transform(X_in)
            if_pred = models["anomaly"].predict(X_scaled)[0]
            if_score = float(models["anomaly"].score_samples(X_scaled)[0])
            is_anomaly_if = (if_pred == -1)
        except Exception as ex:
            print(f"Isolation Forest Error: {ex}")

    # 3. Z-Score
    max_z = abs(mesure.olt_rx_ont_power + 22) / 3.0
    is_anomaly_z = (max_z > 2.5)

    # Label Anomaly Final
    is_anomaly = (is_anomaly_if or is_anomaly_z or is_anomaly_rule_phys or is_anomaly_rule_admin)

    # Attribution de Cluster avec KMeans
    cluster = 1  # Autre/Normal par défaut
    if is_anomaly:
        # Exécuter KMeans sur les 4 puissances de l'anomalie
        if "cluster" in models and "scaler_kmeans" in models:
            try:
                X_c = pd.DataFrame([[
                    float(mesure.olt_power_tx),
                    float(mesure.olt_rx_ont_power),
                    float(mesure.onu_power_tx),
                    float(mesure.onu_power_rx)
                ]], columns=["OLT_POWER_TX", "OLT_RX_ONT_POWER", "ONU_POWER_TX", "ONU_POWER_RX"])
                X_c_scaled = models["scaler_kmeans"].transform(X_c)
                cluster = int(models["cluster"].predict(X_c_scaled)[0])
            except Exception as ex:
                print(f"Clustering KMeans Error: {ex}")

    # Libellés
    type_anomalie = "Normale"
    severite = "NORMALE"
    if is_anomaly:
        if is_anomaly_rule_phys:
            type_anomalie = "Perte de signal (RX < -28dBm)"
            severite = "CRITIQUE"
        elif is_anomaly_rule_admin:
            type_anomalie = "Incoherence administrative (F_SUSP active)"
            severite = "ALERTE"
        elif is_anomaly_z:
            type_anomalie = "Anomalie statistique (Z-Score)"
            severite = "ALERTE"
        else:
            type_anomalie = "Déviation de signal (Isolation Forest)"
            severite = "MODERE"

    # Enregistrer dans la table prediction_anomalie
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prediction_anomalie
                    (date_mesure, score_isolation_forest,
                     label_isolation_forest, score_zscore, label_zscore,
                     label_binaire, anomalie_finale, cluster)
                VALUES
                    (NOW(), :s_if, :l_if, :s_z, :l_z, :lb, :af, :cl)
            """), {
                "s_if": if_score, "l_if": 1 if is_anomaly_if else 0,
                "s_z": max_z, "l_z": 1 if is_anomaly_z else 0,
                "lb": 1 if is_anomaly_rule_admin else 0,
                "af": 1 if is_anomaly else 0,
                "cl": cluster
            })
    except Exception as ex:
        print(f"BD Save Error: {ex}")

    cat = get_category_from_cluster(cluster, type_anomalie)

    # Récupérer les libellés de cluster dynamiques
    if cluster in CLUSTER_NAMES:
        cluster_nom = CLUSTER_NAMES[cluster].upper()
        cluster_description = CLUSTER_DESCRIPTIONS[cluster]
    else:
        cluster_nom = cat
        cluster_description = f"Anomalie classée comme {cat}"

    return PredictionResult(
        anomalie=is_anomaly,
        score=round(max_z, 4),
        cluster=cluster,
        cluster_nom=cluster_nom,
        cluster_description=cluster_description,
        type_anomalie=type_anomalie,
        severite=severite,
        message=(
            f"Anomalie detectee : {type_anomalie} (severite: {severite})"
            if is_anomaly
            else "Mesure normale — aucune anomalie detectee"
        )
    )

# ─────────────────────────────────────────────
# INCIDENTS
# ─────────────────────────────────────────────
@app.get("/api/incidents")
def get_incidents(
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    gouvernorat: str = Query(None, description="Filtrer par gouvernorat")
):
    """Derniers incidents enregistres."""
    
    gouv_eff = effective_gouvernorat_filter(user, gouvernorat)
    where_clause = ""
    params = {"limit": limit}
    
    if gouv_eff:
        where_clause = "WHERE g.gouvernorat = :gouvernorat"
        params["gouvernorat"] = gouv_eff

    query = f"""
        SELECT
            li.id_incident, li.detected_at,
            li.source, li.severite, li.score_zscore, li.statut,
            li.olt_rx_ont_power, li.onu_power_tx,
            f.ml_cluster
        FROM log_incidents li
        LEFT JOIN fait_mesure_olt f ON li.id_ligne = f.id_ligne
        LEFT JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        {where_clause}
        ORDER BY li.detected_at DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [
        {
            "id":              r[0],
            "detected_at":     str(r[1]),
            "source":          r[2],
            "severite":        r[3],
            "score":           float(r[4] or 0),
            "statut":          r[5],
            "olt_rx_ont_power": float(r[6] or 0),
            "onu_power_tx":    float(r[7] or 0),
            "cluster":         int(r[8]) if r[8] is not None else -1
        }
        for r in rows
    ]

# ─────────────────────────────────────────────
# CLUSTERS
# ─────────────────────────────────────────────
@app.get("/api/clusters")
def get_clusters(_user: Dict[str, Any] = Depends(require_admin)):
    """Distribution des clusters ML."""
    query = """
        SELECT
            ml_cluster,
            COUNT(*)                                    AS nb,
            ROUND(AVG(olt_rx_ont_power)::numeric, 2)   AS moy_olt_rx,
            ROUND(AVG(onu_power_tx)::numeric, 2)        AS moy_onu_tx,
            MODE() WITHIN GROUP (ORDER BY ml_type_anomalie) AS type_principal
        FROM fait_mesure_olt
        WHERE ml_anomalie_pred = 1
        AND ml_cluster IS NOT NULL
        GROUP BY ml_cluster
        ORDER BY nb DESC
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query)).fetchall()

    return [
        {
            "cluster":        int(r[0]),
            "nb_anomalies":   int(r[1]),
            "moy_olt_rx":     float(r[2] or 0),
            "moy_onu_tx":     float(r[3] or 0),
            "type_principal": r[4]
        }
        for r in rows
    ]

# ─────────────────────────────────────────────
# STATS TEMPORELLES
# ─────────────────────────────────────────────
@app.get("/api/stats/temporel")
def stats_temporel(_user: Dict[str, Any] = Depends(require_admin)):
    """Evolution des anomalies par jour."""
    query = """
        SELECT
            t.date_seule,
            COUNT(*)                                AS total,
            SUM(f.anomalie)                         AS nb_anomalies,
            ROUND(AVG(f.anomalie::numeric)*100, 2)  AS taux_pct
        FROM fait_mesure_olt f
        JOIN dim_temps t ON f.id_temps = t.id_temps
        WHERE t.date_seule IS NOT NULL
        AND f.anomalie IS NOT NULL
        GROUP BY t.date_seule
        ORDER BY t.date_seule
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query)).fetchall()

    return [
        {
            "date":         str(r[0]),
            "total":        int(r[1]),
            "nb_anomalies": int(r[2]),
            "taux_pct":     float(r[3])
        }
        for r in rows
    ]

# ─────────────────────────────────────────────
# ANALYTIQUE AVANCEE (CUBE ROLAP)
# ─────────────────────────────────────────────
@app.get("/api/stats/scatter")
def stats_scatter(_user: Dict[str, Any] = Depends(get_current_user)):
    """Nuage de points (Scatter) échantillonné depuis le cube (2000 points max)."""
    query = """
        SELECT
            f.olt_rx_ont_power,
            f.onu_power_tx,
            f.anomalie,
            g.gouvernorat
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE f.olt_rx_ont_power IS NOT NULL AND f.onu_power_tx IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 2000
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query)).fetchall()

    return [
        {
            "x": float(r[1]), # ONU_POWER_TX sur l'axe X
            "y": float(r[0]), # OLT_RX_POWER sur l'axe Y
            "anomalie": bool(r[2]),
            "gouvernorat": r[3]
        }
        for r in rows
    ]

@app.get("/api/stats/radar")
def stats_radar(_user: Dict[str, Any] = Depends(get_current_user)):
    """Radar de Santé comparant chaque gouvernorat aux métriques globales (ROLAP slice & dice)."""
    query = """
        SELECT
            g.gouvernorat,
            ROUND(AVG(f.olt_rx_ont_power)::numeric, 2) AS moy_olt_rx,
            ROUND(AVG(f.anomalie_technique::numeric)*100, 2) AS taux_tech,
            ROUND(AVG(f.anomalie_admin::numeric)*100, 2) AS taux_admin,
            ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_global
        FROM fait_mesure_olt f
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        GROUP BY g.gouvernorat
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query)).fetchall()

    return [
        {
            "gouvernorat": r[0],
            "moy_olt_rx": float(r[1] or 0),
            "taux_tech": float(r[2] or 0),
            "taux_admin": float(r[3] or 0),
            "taux_global": float(r[4] or 0)
        }
        for r in rows
    ]

@app.get("/api/stats/causes-marques")
def stats_causes_marques(user: Dict[str, Any] = Depends(get_current_user)):
    """Matrice 2D (Marque x Cluster) pour Stacked Bar Chart."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params = {}
    if eff_gouv: params["gouv"] = eff_gouv

    query = f"""
        SELECT
            c.marque,
            f.ml_cluster,
            f.ml_type_anomalie,
            COUNT(*) as nb
        FROM fait_mesure_olt f
        JOIN dim_olt_chassis c ON f.id_chss_olt = c.id_chss_olt
        JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
        WHERE f.anomalie = 1 {filt}
        GROUP BY c.marque, f.ml_cluster, f.ml_type_anomalie
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    result = {}
    for r in rows:
        m = str(r[0]).upper()
        if "HUAWEI" in m: marque = "HUAWEI"
        elif "ALCATEL" in m: marque = "ALCATEL"
        else: continue

        cluster = get_category_from_cluster(r[1], r[2])
        if marque not in result:
            result[marque] = {"PORT": 0, "CARTE": 0, "ADMIN": 0, "AUTRE": 0}
        result[marque][cluster] += int(r[3])

    # S'assurer que les 2 marques existent même s'il n'y a pas d'anomalies
    if "HUAWEI" not in result: result["HUAWEI"] = {"PORT": 0, "CARTE": 0, "ADMIN": 0, "AUTRE": 0}
    if "ALCATEL" not in result: result["ALCATEL"] = {"PORT": 0, "CARTE": 0, "ADMIN": 0, "AUTRE": 0}

    return result

# ─────────────────────────────────────────────
# ADMIN — GESTION DES TECHNICIENS
# ─────────────────────────────────────────────
@app.get("/api/admin/techniciens")
def admin_get_techniciens(_user: Dict[str, Any] = Depends(require_admin)):
    """Liste des techniciens avec nb d'anomalies à corriger ce mois (admin only)."""
    with engine.connect() as conn:
        # Liste des techniciens
        tech_rows = conn.execute(text("""
            SELECT id, username, email, assigned_gouvernorat
            FROM app_user
            WHERE role = 'technicien'
            ORDER BY username
        """)).fetchall()

        # Anomalies du mois courant par gouvernorat
        anom_rows = conn.execute(text("""
            SELECT
                g.gouvernorat,
                COUNT(*) AS nb_anomalies_mois,
                ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_pct
            FROM fait_mesure_olt f
            JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            JOIN dim_temps t ON f.id_temps = t.id_temps
            WHERE f.anomalie = 1
              AND DATE_TRUNC('month', t.date_mesure) = DATE_TRUNC('month', CURRENT_DATE)
            GROUP BY g.gouvernorat
        """)).fetchall()

    # Map gouvernorat → stats
    anom_map = {r[0]: {"nb": int(r[1]), "taux": float(r[2] or 0)} for r in anom_rows}

    return [
        {
            "id": r[0],
            "username": r[1],
            "email": r[2],
            "gouvernorat": r[3] or "—",
            "nb_anomalies_mois": anom_map.get(r[3], {}).get("nb", 0),
            "taux_anomalie_mois": anom_map.get(r[3], {}).get("taux", 0.0),
        }
        for r in tech_rows
    ]

# ─────────────────────────────────────────────
# ANALYSE HIERARCHIQUE (Cube ROLAP — Drill-Down)
# ─────────────────────────────────────────────
@app.get("/api/stats/hierarchique")
def stats_hierarchique(user: Dict[str, Any] = Depends(get_current_user)):
    """Analyse hiérarchique Gouvernorat → Centrale → Chassis OLT."""
    eff_gouv = effective_gouvernorat_filter(user, None)
    filt = "" if not eff_gouv else " AND g.gouvernorat = :gouv "
    params = {}
    if eff_gouv: params["gouv"] = eff_gouv

    with engine.connect() as conn:
        # Niveau 1 : Gouvernorat
        gouv_rows = conn.execute(text(f"""
            SELECT
                g.gouvernorat,
                COUNT(*) AS nb_anomalies,
                ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_pct,
                ROUND(AVG(f.olt_rx_ont_power)::numeric, 2) AS moy_olt_rx
            FROM fait_mesure_olt f
            JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            WHERE f.anomalie = 1 {filt}
            GROUP BY g.gouvernorat
            ORDER BY nb_anomalies DESC
        """), params).fetchall()

        # Niveau 2 : Centrale
        cent_rows = conn.execute(text(f"""
            SELECT
                g.gouvernorat,
                c.centrale,
                COUNT(*) AS nb_anomalies,
                ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_pct,
                ROUND(AVG(f.olt_rx_ont_power)::numeric, 2) AS moy_olt_rx
            FROM fait_mesure_olt f
            JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            JOIN dim_centrale c ON f.id_co = c.id_co
            WHERE f.anomalie = 1 {filt}
            GROUP BY g.gouvernorat, c.centrale
            ORDER BY g.gouvernorat, nb_anomalies DESC
        """), params).fetchall()

        # Niveau 3 : Chassis OLT
        chassis_rows = conn.execute(text(f"""
            SELECT
                g.gouvernorat,
                c.centrale,
                ch.host_name,
                COUNT(*) AS nb_anomalies,
                ROUND(AVG(f.anomalie::numeric)*100, 2) AS taux_pct,
                ROUND(AVG(f.olt_rx_ont_power)::numeric, 2) AS moy_olt_rx
            FROM fait_mesure_olt f
            JOIN dim_gouvernorat g ON f.codgouv = g.codgouv
            JOIN dim_centrale c ON f.id_co = c.id_co
            JOIN dim_olt_chassis ch ON f.id_chss_olt = ch.id_chss_olt
            WHERE f.anomalie = 1 {filt}
            GROUP BY g.gouvernorat, c.centrale, ch.host_name
            ORDER BY g.gouvernorat, c.centrale, nb_anomalies DESC
        """), params).fetchall()

    # Build centrales map: gouvernorat → liste de centrales
    centrales_map: Dict[str, list] = {}
    for r in cent_rows:
        gouv = r[0]
        if gouv not in centrales_map:
            centrales_map[gouv] = []
        centrales_map[gouv].append({
            "centrale": r[1], "nb_anomalies": int(r[2]),
            "taux_pct": float(r[3] or 0), "moy_olt_rx": float(r[4] or 0),
            "chassis": []
        })

    # Build chassis map: (gouvernorat, centrale) → chassis list
    for r in chassis_rows:
        gouv, cent = r[0], r[1]
        if gouv in centrales_map:
            for c in centrales_map[gouv]:
                if c["centrale"] == cent:
                    c["chassis"].append({
                        "host_name": r[2], "nb_anomalies": int(r[3]),
                        "taux_pct": float(r[4] or 0), "moy_olt_rx": float(r[5] or 0)
                    })
                    break

    result = []
    total_anom = 0
    for r in gouv_rows:
        gouv = r[0]
        nb = int(r[1])
        total_anom += nb
        result.append({
            "gouvernorat": gouv,
            "nb_anomalies": nb,
            "taux_pct": float(r[2] or 0),
            "moy_olt_rx": float(r[3] or 0),
            "centrales": centrales_map.get(gouv, [])
        })

    return {"rows": result, "total_anomalies": total_anom}


# ─────────────────────────────────────────────
# FLUX ANALYTIQUE (IMPORT/EXPORT EN LOT ML)
# ─────────────────────────────────────────────
TEMP_EXPORTS_DIR = os.path.join(BASE_DIR, "temp_exports")
os.makedirs(TEMP_EXPORTS_DIR, exist_ok=True)

@app.post("/api/admin/analyze-file")
def analyze_file(
    file: UploadFile = File(...),
    admin_user: Dict[str, Any] = Depends(require_admin)
):
    """
    Import, run ML pipeline (Isolation Forest + Z-Score + Rules + K-Means Clustering)
    on a raw network measurements file, and save the enriched result for export.
    """
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in [".xlsx", ".xls", ".csv"]:
        raise HTTPException(
            status_code=400,
            detail="Format de fichier non supporté. Veuillez fournir un fichier Excel (.xlsx, .xls) ou CSV."
        )
        
    try:
        # Read the file
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file.file)
        else:
            df = pd.read_csv(file.file)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors de la lecture du fichier : {str(e)}"
        )
        
    # Check minimum required columns (case-insensitive mapping)
    col_mapping = {c.lower().strip(): c for c in df.columns}
    required = ["olt_power_tx", "olt_rx_ont_power", "onu_power_tx", "onu_power_rx"]
    missing = [r for r in required if r not in col_mapping]
    
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes requises manquantes : {', '.join(missing).upper()}. Reçu : {list(df.columns)}"
        )
        
    # Standardize column casing for easier processing
    # Create internal columns with correct casing
    for r in required:
        orig_name = col_mapping[r]
        df[r] = pd.to_numeric(df[orig_name], errors='coerce').fillna(0.0)
        
    # Other optional columns
    for opt in ["f_susp", "admin_status", "oper_status", "id_carte_olt", "no_port", "onu_id", "gouvernorat"]:
        if opt in col_mapping:
            df[opt] = df[col_mapping[opt]]
        else:
            if opt in ["f_susp", "admin_status", "oper_status"]:
                df[opt] = 1 if opt == "admin_status" or opt == "oper_status" else 0
            elif opt == "gouvernorat":
                df[opt] = "SFAX"
            else:
                df[opt] = 1
                
    # Ensure they are numeric/valid
    df["f_susp"] = pd.to_numeric(df["f_susp"], errors='coerce').fillna(0).astype(int)
    df["admin_status"] = pd.to_numeric(df["admin_status"], errors='coerce').fillna(1).astype(int)
    df["oper_status"] = pd.to_numeric(df["oper_status"], errors='coerce').fillna(1).astype(int)
    
    # ── 1. EXÉCUTION DU PIPELINE ML ──
    # A. Isolation Forest
    is_anomaly_if = np.zeros(len(df), dtype=bool)
    if_scores = np.zeros(len(df), dtype=float)
    
    if "anomaly" in models and "scaler" in models:
        try:
            X = df[required].copy()
            X.columns = ["OLT_POWER_TX", "OLT_RX_ONT_POWER", "ONU_POWER_TX", "ONU_POWER_RX"]
            X_scaled = models["scaler"].transform(X)
            preds = models["anomaly"].predict(X_scaled)
            is_anomaly_if = (preds == -1)
            if_scores = models["anomaly"].score_samples(X_scaled)
        except Exception as ex:
            print(f"Batch Isolation Forest Error: {ex}")
            
    # B. Z-Score & Rules
    df["z_score"] = abs(df["olt_rx_ont_power"] + 22) / 3.0
    is_anomaly_z = (df["z_score"] > 2.5)
    
    is_anomaly_rule_phys = (df["olt_rx_ont_power"] < -28)
    is_anomaly_rule_admin = (df["f_susp"] > 0) & (df["admin_status"] == 1)
    
    # Combined Anomaly Label
    df["anomalie_predicted"] = (is_anomaly_if | is_anomaly_z | is_anomaly_rule_phys | is_anomaly_rule_admin).astype(int)
    
    # C. Clustering K-Means on detected anomalies
    card_col = col_mapping.get("id_carte_olt", None)
    port_col = col_mapping.get("no_port", None)
    
    if card_col and port_col:
        df["card_fault_rate"] = df.groupby([card_col])["anomalie_predicted"].transform("mean")
        df["port_fault_rate"] = df.groupby([card_col, port_col])["anomalie_predicted"].transform("mean")
    else:
        df["card_fault_rate"] = df["anomalie_predicted"].mean()
        df["port_fault_rate"] = df["anomalie_predicted"].mean()
        
    df["Anomalie_admin_bin"] = ((df["f_susp"] > 0) & (df["admin_status"] == 1)).astype(int)
    
    # Assign cluster labels
    df["cluster_id"] = 1 # default Autre/Normal
    df["cluster_category"] = "AUTRE"
    df["anomaly_type"] = "Normale"
    df["severite"] = "NORMALE"
    
    anom_mask = df["anomalie_predicted"] == 1
    if anom_mask.any() and "cluster" in models and "scaler_kmeans" in models:
        try:
            X_clust = df.loc[anom_mask, required].copy()
            X_clust.columns = ["OLT_POWER_TX", "OLT_RX_ONT_POWER", "ONU_POWER_TX", "ONU_POWER_RX"]
            
            X_clust_scaled = models["scaler_kmeans"].transform(X_clust)
            preds_clust = models["cluster"].predict(X_clust_scaled)
            df.loc[anom_mask, "cluster_id"] = preds_clust.astype(int)
            
            # Map category name
            df.loc[anom_mask, "cluster_category"] = df.loc[anom_mask, "cluster_id"].map(
                lambda cid: CLUSTER_NAMES.get(cid, "AUTRE").upper()
            )
        except Exception as ex:
            print(f"Batch Clustering Error: {ex}")
            
    # Refine anomaly descriptions and severities
    df.loc[anom_mask & is_anomaly_rule_phys, "anomaly_type"] = "Perte de signal (RX < -28dBm)"
    df.loc[anom_mask & is_anomaly_rule_phys, "severite"] = "CRITIQUE"
    
    df.loc[anom_mask & is_anomaly_rule_admin, "anomaly_type"] = "Incohérence administrative"
    df.loc[anom_mask & is_anomaly_rule_admin, "severite"] = "ALERTE"
    
    normal_anoms = anom_mask & ~is_anomaly_rule_phys & ~is_anomaly_rule_admin
    df.loc[normal_anoms & is_anomaly_z, "anomaly_type"] = "Anomalie statistique (Z-Score)"
    df.loc[normal_anoms & is_anomaly_z, "severite"] = "ALERTE"
    
    df.loc[normal_anoms & ~is_anomaly_z & is_anomaly_if, "anomaly_type"] = "Déviation de signal (Isolation Forest)"
    df.loc[normal_anoms & ~is_anomaly_z & is_anomaly_if, "severite"] = "MODERE"
    
    # ── 2. SAVE ENRICHED FILE ──
    file_token = str(uuid.uuid4())
    enriched_filename = f"analyse_ml_{file_token}{ext}"
    enriched_path = os.path.join(TEMP_EXPORTS_DIR, enriched_filename)
    
    # Save the file containing original plus enriched columns
    export_df = df.copy()
    
    # Rename/add clean export columns
    export_df["ML_Anomalie_Detectee"] = export_df["anomalie_predicted"]
    export_df["ML_Score_Anomalie"] = if_scores
    export_df["ML_Z_Score"] = export_df["z_score"]
    export_df["ML_Cluster_ID"] = export_df["cluster_id"]
    export_df["ML_Cause_Cluster"] = export_df["cluster_category"]
    export_df["ML_Type_Dysfonctionnement"] = export_df["anomaly_type"]
    export_df["ML_Severite"] = export_df["severite"]
    
    # Remove temporary internal columns if they weren't in the original file
    internal_cols = ["anomalie_predicted", "z_score", "cluster_id", "cluster_category", "anomaly_type", "severite", "card_fault_rate", "port_fault_rate", "Anomalie_admin_bin"]
    for c in internal_cols:
        if c in export_df.columns and c not in df.columns:
            export_df.drop(columns=[c], inplace=True)
            
    if ext in [".xlsx", ".xls"]:
        export_df.to_excel(enriched_path, index=False)
    else:
        export_df.to_csv(enriched_path, index=False)
        
    # ── 3. SYNTHESIS SUMMARY FOR FRONTEND ──
    total_records = len(df)
    total_anomalies = int(df["anomalie_predicted"].sum())
    nb_tech = int(((df["anomalie_predicted"] == 1) & (~is_anomaly_rule_admin)).sum())
    nb_admin = int(((df["anomalie_predicted"] == 1) & is_anomaly_rule_admin).sum())
    
    # Cluster counts
    cluster_counts = df.loc[anom_mask, "cluster_category"].value_counts().to_dict()
    
    # Detailed sample list to preview
    samples = []
    sample_rows = df[df["anomalie_predicted"] == 1].head(50)
    for idx, r in sample_rows.iterrows():
        samples.append({
            "row_index": int(idx + 2),
            "olt_power_tx": float(r["olt_power_tx"]),
            "olt_rx_ont_power": float(r["olt_rx_ont_power"]),
            "onu_power_tx": float(r["onu_power_tx"]),
            "onu_power_rx": float(r["onu_power_rx"]),
            "cause": str(r["cluster_category"]),
            "type_dysfonctionnement": str(r["anomaly_type"]),
            "severite": str(r["severite"]),
            "gouvernorat": str(r.get("gouvernorat", "SFAX"))
        })
        
    return {
        "success": True,
        "filename": filename,
        "file_token": file_token,
        "summary": {
            "total_records": total_records,
            "total_anomalies": total_anomalies,
            "taux_anomalie": round((total_anomalies / total_records) * 100, 2) if total_records > 0 else 0.0,
            "nb_tech": nb_tech,
            "nb_admin": nb_admin,
            "clusters": {
                "PORT": int(cluster_counts.get("PORT", 0)),
                "CARTE": int(cluster_counts.get("CARTE", 0)),
                "ADMIN": int(cluster_counts.get("ADMIN", 0)),
                "AUTRE": int(cluster_counts.get("AUTRE", 0))
            }
        },
        "anomalies_preview": samples
    }

@app.get("/api/admin/download-analysis/{file_token}")
def download_analysis(file_token: str):
    """
    Download the enriched batch analysis file.
    """
    for f in os.listdir(TEMP_EXPORTS_DIR):
        if file_token in f:
            filepath = os.path.join(TEMP_EXPORTS_DIR, f)
            if f.endswith(".xlsx"):
                media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif f.endswith(".xls"):
                media_type = "application/vnd.ms-excel"
            else:
                media_type = "text/csv"
            return FileResponse(
                filepath, 
                media_type=media_type, 
                filename=f"supervision_gpon_enrichi_{f}"
            )
            
    raise HTTPException(status_code=404, detail="Fichier d'analyse expiré ou inexistant.")

# ─────────────────────────────────────────────
# SERVIR LE FRONTEND (À LA FIN)
# ─────────────────────────────────────────────
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

@app.get("/{filename}")
def serve_static(filename: str):
    """Sert les fichiers statiques (html, css, js) s'ils existent."""
    filepath = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(filepath):
        if filename.endswith(".html"): mt = "text/html"
        elif filename.endswith(".css"): mt = "text/css"
        elif filename.endswith(".js"): mt = "application/javascript"
        else: mt = "application/octet-stream"
        return FileResponse(filepath, media_type=mt)
    # Si le fichier n'existe pas, on redirige vers index.html
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"), media_type="text/html")

# Montage de sécurité
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
