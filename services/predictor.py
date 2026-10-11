import pickle
import os
import pandas as pd
import numpy as np

class XPONPredictor:
    def __init__(self, models_dir='models'):
        self.models_dir = models_dir
        self.anomaly_config = None
        self.clustering_data = None
        self._load_models()

    def _load_models(self):
        """Charge les modeles de production (Z-Score + Clustering K-Means)."""
        try:
            # Modele de detection (Z-Score + Regles)
            with open(os.path.join(self.models_dir, 'anomaly_model.pkl'), 'rb') as f:
                self.anomaly_config = pickle.load(f)
            
            # Modele de diagnostic (Clustering)
            with open(os.path.join(self.models_dir, 'clustering_model.pkl'), 'rb') as f:
                self.clustering_data = pickle.load(f)
                
            print("--- Modeles XPON (Z-Score + K-Means) charges avec succes ---")
        except Exception as e:
            print(f"Erreur lors du chargement des modeles : {e}")

    def predict(self, input_data):
        """
        Inference hybride :
        1. Calcul du Z-Score sur les mesures physiques.
        2. Verification des Regles Metier (Admin/Oper).
        3. Diagnostic via K-Means si une anomalie est detectee.
        """
        if self.anomaly_config is None or self.clustering_data is None:
            return {"error": "Modeles non initialises."}

        features = self.anomaly_config['features']
        
        # --- A. Branche Z-Score (Statistique) ---
        z_scores = []
        for f in features:
            val = input_data.get(f, 0)
            mean = self.anomaly_config['means'][f]
            std = self.anomaly_config['stds'][f]
            z = abs((val - mean) / std)
            z_scores.append(z)
        
        max_z = max(z_scores)
        is_z_anomaly = max_z > self.anomaly_config['threshold']

        # --- B. Branche Regles Metier ---
        a = input_data.get('ADMIN_STATUS', 1)
        o = input_data.get('OPER_STATUS', 1)
        # Exemple de regle : Si status == 2 (Down/Error)
        is_rule_anomaly = (a == 2 or o == 2)

        # --- C. Decision Finale (Union) ---
        is_anomaly = is_z_anomaly or is_rule_anomaly

        # --- D. Diagnostic (Clustering) ---
        result = {
            "is_anomaly": is_anomaly,
            "max_z_score": round(max_z, 2),
            "detection_source": "Z-Score" if is_z_anomaly else ("Regles" if is_rule_anomaly else "Aucune"),
            "type_anomalie": "Normal",
            "cluster_id": None
        }

        if is_anomaly:
            # On prepare les donnees pour le clustering
            measures_df = pd.DataFrame([[input_data[f] for f in features]], columns=features)
            
            # Mise a l'echelle via le scaler enregistre
            X_scaled = self.clustering_data['scaler'].transform(measures_df)
            
            # Prediction du cluster
            cluster_id = int(self.clustering_data['model'].predict(X_scaled)[0])
            result["cluster_id"] = cluster_id
            
            # Recuperation du nom metier (PORT, CARTE, ADMIN, AUTRE)
            result["type_anomalie"] = self.clustering_data['mapping'].get(cluster_id, "Inconnu")

        return result

if __name__ == "__main__":
    # Test rapide du nouveau moteur
    predictor = XPONPredictor()
    
    # Cas Normal
    test_ok = {
        'OLT_POWER_TX': 3.5, 'OLT_RX_ONT_POWER': -11.0, 
        'ONU_POWER_TX': 2.7, 'ONU_POWER_RX': -11.0,
        'ADMIN_STATUS': 1, 'OPER_STATUS': 1
    }
    print(f"Test Normal : {predictor.predict(test_ok)}")
    
    # Cas Anomalie Technique (Forte attenuation)
    test_anom = {
        'OLT_POWER_TX': 3.5, 'OLT_RX_ONT_POWER': -35.0, 
        'ONU_POWER_TX': 2.7, 'ONU_POWER_RX': -40.0,
        'ADMIN_STATUS': 1, 'OPER_STATUS': 1
    }
    print(f"Test Anomalie : {predictor.predict(test_anom)}")
