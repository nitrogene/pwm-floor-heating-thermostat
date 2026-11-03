# Roadmap & Spécifications de Développement (TODO.md)

Ce document retrace la feuille de route, les spécifications algorithmiques et les chantiers de développement du composant **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`).

---

## 1. Moteur & Modélisation Thermodynamique

- [x] **Projection de trajectoire avec temps mort ($\theta$) :**
  - [x] Calculer la pente filtrée $dT/dt$ (°C/h) par régression linéaire robuste sur fenêtre glissante (60 min).
  - [x] Calculer la température projetée : $T_{\text{proj}}(t + \theta) = T_{\text{amb}}(t) + \theta \cdot \frac{dT_{\text{amb}}}{dt}$.
  - [x] Détecter la rupture de pente (creux thermique matinal) $\theta$ heures à l'avance pour déclencher l'allumage avant que l'ambiance ne passe sous la consigne minimale.
  - [x] Exposition des attributs télémétriques `temp_derivative_hourly` et `temp_projected_ahead`.
- [ ] **Modélisation des apports et pertes dynamiques :**
  - [ ] Intégration du vent (sur-déperditions convectives sur l'enveloppe).
  - [ ] Intégration du rayonnement solaire (capteur de luminosité ou prévision météo d'ensoleillement W/m²) pour inhiber les relances matinales inutiles les jours ensoleillés.
- [ ] **Couplage convectif inter-zones :**
  - [ ] Modéliser le transfert thermique passif entre zones communicantes (ex: flux d'air chaud ascendant du Salon vers la mezzanine du Bureau).
  - [ ] Coordinateur multi-zones optionnel pour lisser l'appel de puissance électrique (éviter d'allumer tous les compresseurs simultanément).
- [ ] **Auto-étalonnage & Apprentissage continu :**
  - [ ] Recalcul périodique des déperditions $H$ ($\text{W/K}$) par régression linéaire sur les phases de refroidissement libre nocturne ($dT/dt$ vs $\Delta T_{\text{int-ext}}$).
  - [ ] Ajustement dynamique de la constante de temps de dalle $\tau$ et du temps mort $\theta$.

---

## 2. Ordonnancement Énergétique, FSM & Modes de Fonctionnement

- [x] **Machine à états finis Danfoss (Garde matérielle) :**
  - [x] Minimum ON cycle : 30 minutes (retour d'huile obligatoire dans le carter).
  - [x] Minimum OFF cycle : 15 minutes (égalisation des pressions frigorifiques BP/HP).
  - [x] Budget maximal de cycles journaliers (anti-fatigue mécanique, max 6 cycles/jour).
- [x] **Shadow Mode & Dry-Run (Simulation Passive Jumeau Numérique) :**
  - [x] Option `dry_run: true` garantissant qu'aucun ordre physique n'est envoyé aux actionneurs.
  - [x] Support d'un actionneur virtuel (`input_boolean.*`) pour visualiser l'état simulé en direct dans l'UI.
  - [x] Paramètre `observed_heater` pour écouter et comparer les activations du vrai thermostat PID en parallèle.
  - [x] Attributs d'explicabilité : `simulated_heater_state`, `decision_reason` et `dry_run`.
- [x] **Planchers chauffants hydrauliques & Sonde de boucle d'eau :**
  - [x] Support optionnel du paramètre `floor_temp_sensor` (mesure directe de l'eau de retour de boucle).
  - [x] Coupure d'urgence anti-surchauffe dalle `max_floor_temp` (défaut 28.0°C conforme à la norme DTU 65.14).
  - [x] Protection hors-gel plancher `min_floor_temp` (défaut 14.0°C).
  - [x] Attributs télémétriques `floor_temperature`, `max_floor_temperature`, `min_floor_temperature`.
- [ ] **Optimisation tarifaire Heures Creuses (Linky TIC) :**
  - [ ] Allocation prioritaire du quota thermique journalier pendant les Heures Creuses nocturnes.
  - [ ] Modulation de la durée des cycles PWM (ex: cycles de 2h30 en HC vs cycles de 45 min en HP si besoin impérieux).
- [ ] **Superviseur d'ambiance à dérive lente (Sans Integral Windup) :**
  - [ ] Correction proportionnelle douce et bornée sur le quota d'énergie journalier.
  - [ ] Suppression définitive de l'intégrateur continu divergent.

---

## 3. Télémétrie Avancée & Données de Debug pour Calage IA (Auto-Tuning)

- [ ] **Métrique reine d'erreur de modèle ($e_{\text{modèle}}$) :**
  - [ ] Historiser $e_{\text{modèle}}(t) = T_{\text{mesurée}}(t) - T_{\text{projetée}}(t - \theta)$ pour permettre aux agents IA de quantifier immédiatement l'erreur d'estimation des déperditions $H$ ou le déphasage de $\theta$.
- [ ] **Exposition des variables internes du modèle physique :**
  - [ ] `temp_projected_ahead` : Température anticipée à $t + \theta$ (°C).
  - [ ] `temp_derivative_hourly` : Dérivée filtrée de température $dT/dt$ (°C/h).
  - [ ] `estimated_slab_energy_kwh` : Énergie thermique estimée emmagasinée dans la dalle (kWh).
  - [ ] `daily_energy_quota_kwh` : Quota thermique requis calculé sur 24h selon prévisions météo.
  - [ ] `energy_delivered_today_kwh` : Énergie thermique utile injectée depuis minuit.
  - [ ] `duty_cycle_continuous` : Rapport cyclique PWM théorique demandé (0 à 100%).
- [ ] **Relevé automatique des pentes d'identification (Données d'apprentissage) :**
  - [ ] `unheated_cooling_rate` : Taux de refroidissement passif (°C/h) identifiant $H / C_{\text{dalle}}$.
  - [ ] `active_heating_rate` : Taux de montée active en chauffe (°C/h) identifiant $P_{\text{watts}} / C_{\text{dalle}}$.
  - [ ] `outdoor_delta_avg` : $\Delta T_{\text{int-ext}}$ moyen associé.
- [ ] **Instrumentation FSM & Diagnostic :**
  - [ ] `fsm_state` (`idle`, `running_min_lock`, `running_normal`, `waiting_min_off`).
  - [ ] `current_cycle_elapsed_min` et `current_cycle_target_min`.
  - [ ] `cycles_count_today` et `max_cycles_budget`.
  - [ ] `time_to_next_allowed_start` (décompte d'égalisation de pression 15 min).
- [ ] **Architecture d'exposition Home Assistant :**
  - [ ] Présence de l'intégralité des indicateurs dans les `extra_state_attributes` de l'entité Climate.
  - [ ] Support d'une option `debug: true` instanciant automatiquement les entités de diagnostic `sensor.<nom>_*` dédiées (historisation native SQLite / InfluxDB sans template externe).

---

## 4. Qualité Logicielle, Tests & Écosystème HACS

- [x] **Compatibilité HACS :**
  - [x] `hacs.json` configuré avec `"content_in_root": true`.
  - [x] Structure de distribution autonome et documentation `README.md`.
- [x] **Validation CI/CD (GitHub Actions) :**
  - [x] Workflow de validation `hassfest` (Home Assistant Manifest Validator).
  - [x] Workflow de validation `hacs` (HACS Action).
  - [x] Workflow de contrôle de style et typage (`ruff check`).
  - [x] Tests unitaires automatisés (`pytest`) validant la FSM Danfoss, la régression linéaire et les sécurités DTU 65.14.
- [x] **Traductions et métadonnées d'entités :**
  - [x] Fichier racine `strings.json`.
  - [x] Traductions complètes en anglais (`translations/en.json`) et en français (`translations/fr.json`).
- [ ] **Config Flow (Interface UI Home Assistant) :**
  - [ ] Implémenter `config_flow.py` pour permettre l'ajout du thermostat directement depuis l'interface graphique de Home Assistant (sans YAML obligatoire).
