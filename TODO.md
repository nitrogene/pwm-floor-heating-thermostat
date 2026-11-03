# Roadmap & Spécifications de Développement (TODO.md)

Ce document retrace la feuille de route, les spécifications algorithmiques et les chantiers de développement du composant **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`).

---

## 1. Moteur & Modélisation Thermodynamique

- [ ] **Projection de trajectoire avec temps mort ($\theta$) :**
  - [ ] Calculer la température projetée : $T_{\text{proj}}(t + \theta) = T_{\text{amb}}(t) + \theta \cdot \frac{dT_{\text{amb}}}{dt}$.
  - [ ] Détecter la rupture de pente (creux thermique matinal) $\theta$ heures à l'avance pour déclencher l'allumage avant que l'ambiance ne passe sous la consigne minimale.
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

## 2. Ordonnancement Énergétique & Machine à États Finis (FSM)

- [x] **Machine à états finis Danfoss (Garde matérielle) :**
  - [x] Minimum ON cycle : 30 minutes (retour d'huile obligatoire dans le carter).
  - [x] Minimum OFF cycle : 15 minutes (égalisation des pressions frigorifiques BP/HP).
  - [x] Budget maximal de cycles journaliers (anti-fatigue mécanique, max 6 cycles/jour).
- [ ] **Optimisation tarifaire Heures Creuses (Linky TIC) :**
  - [ ] Allocation prioritaire du quota thermique journalier pendant les Heures Creuses nocturnes.
  - [ ] Modulation de la durée des cycles PWM (ex: cycles de 2h30 en HC vs cycles de 45 min en HP si besoin impérieux).
- [ ] **Superviseur d'ambiance à dérive lente (Sans Integral Windup) :**
  - [ ] Correction proportionnelle douce et bornée sur le quota d'énergie journalier.
  - [ ] Suppression définitive de l'intégrateur continu divergent.

---

## 3. Qualité Logicielle, Tests & Écosystème HACS

- [x] **Compatibilité HACS :**
  - [x] `hacs.json` configuré avec `"content_in_root": true`.
  - [x] Structure de distribution autonome et documentation `README.md`.
- [ ] **Validation CI/CD (GitHub Actions) :**
  - [ ] Workflow de validation `hassfest` (Home Assistant Manifest Validator).
  - [ ] Workflow de contrôle de style et typage (`ruff`, `flake8`, `mypy`).
  - [ ] Tests unitaires automatisés (`pytest-homeassistant-custom-component`) pour valider la FSM et les transitions d'états.
- [ ] **Config Flow (Interface UI Home Assistant) :**
  - [ ] Implémenter `config_flow.py` pour permettre l'ajout du thermostat directement depuis l'interface graphique de Home Assistant (sans YAML obligatoire).
  - [ ] Support des traductions (`strings.json`, `fr.json`, `en.json`).
