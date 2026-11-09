# Revue de code — pwm-floor-heating-thermostat

**Version revue** : v0.2.2 (commit `ec84f42`, 8 nov. 2026)
**Périmètre** : `climate.py`, `config_flow.py`, `sensor.py`, `diagnostics.py`, `const.py`, `strings.json` + traductions, `tests/`, CI (`.github/workflows/`), documentation.
**Verdict global** : 🟢 Projet solide et bien structuré, prêt pour HACS après correction de 3 bugs bloquants.

## Points forts

- **Structure HACS standard** (`custom_components/`), manifest complet (`iot_class`, `config_flow`), config flow + options flow natifs, traductions en/fr synchronisées avec `strings.json`.
- **CI complète** : hassfest, action HACS, ruff, pytest (`validate.yaml`), release automatisée sur tag `v*` avec extraction des notes depuis `CHANGELOG.md` (`release.yaml`).
- **FSM de sécurité bien conçue** : les verrous 30 min ON / 15 min OFF sont inviolables dans `_async_start_heating_safe()` / `_async_stop_heating_safe()` ; logique de promotion d'état propre (`RUNNING_MIN_LOCK → RUNNING_NORMAL`, `WAITING_MIN_OFF → IDLE`).
- **Explainabilité** : attribut `decision_reason`, télémétrie riche, mode shadow/dry-run avec `observed_heater` pour le benchmark comparatif — excellente approche pour la validation terrain.
- **Maths saines** : régression linéaire bornée ±3 °C/h, projection à t+θ, calcul de `model_error` par interpolation à t−θ, filtrage IIR de calibrage borné [0.3·H, 3·H].
- **Documentation exceptionnelle** : les justifications physiques (retour d'huile, égalisation HP/BP, DTU 65.14) sont d'un niveau de détail rare.

## 🔴 Bugs bloquants

### 1. `max_cycles_per_day` n'est jamais appliqué

`self._max_cycles` est assigné dans `__init__` (ligne ~226) puis jamais relu. Le README et TODO.md cochent « max 6 cycles/jour anti-fatigue » comme *done*, mais la sécurité **n'existe pas dans le code**. C'est le seul garde-fou Danfoss manquant à l'appel.

**Fix** : dans `_async_start_heating_safe()`, refuser le démarrage si `self._cycles_today >= self._max_cycles` (avec reason dédiée).

### 2. `diagnostics.py` : la plupart des champs retournent `null`

Les noms lus via `getattr` ne correspondent pas aux attributs réels de l'entité :

| Diagnostics lit | Attribut réel |
|---|---|
| `_temp_derivative_hourly` | `_temp_derivative` |
| `_temp_projected_ahead` | `_temp_projected` |
| `_energy_quota_24h_kwh` | `_energy_needed_kwh` |
| `_heating_hours_needed_24h` | `_hours_needed_24h` |
| `_heating_hours_done_today` | `_hours_run_today` |
| `_daily_quota_blocked` | `_quota_blocked` |
| `_window_open_detected` | `_window_open` |
| `_window_detection_active` | `_window_detection_enabled` |
| `_heat_loss_factor_wk` | `_heat_loss` |
| `_compressor_power_watts` | `_power_watts` |
| `_compressor_cycles_today` | `_cycles_today` |
| `_stagger_delay_sec` | inexistant (`_stagger_delay` est un timedelta) |

Une douzaine de champs du bouton « Télécharger les diagnostics » sont silencieusement vides. Accessoirement, `TO_REDACT` est vide alors que le TODO annonce une rédaction automatique des tokens.

**Fix** : réaligner les noms, ou mieux : lire directement depuis `extra_state_attributes` de l'entité.

### 3. Restauration d'état FSM incohérente après redémarrage

`fsm_state` est restauré depuis les attributs, mais `_last_state_change` est réinitialisé à `utcnow()`. Conséquences si HA redémarre en plein `running_min_lock` :

- le verrou 30 min repart de zéro ;
- la FSM croit que le compresseur tourne alors que le relais n'a pas été piloté → arrêt impossible jusqu'à 30 min, `hvac_action` désynchronisé ;
- `_cycle_start_time` est `None` → comptabilisation des heures faussée.

**Fix** : restaurer systématiquement vers `WAITING_MIN_OFF` (position sûre), et resynchroniser l'état du relais.

## 🟠 Risques de conception

- **Surcharge de `async_write_ha_state()`** pour émettre le signal dispatcher : fragile, HA appelle aussi cette méthode en interne (restore, teardown). Un `DataUpdateCoordinator`, ou des capteurs lisant l'entité via `async_track_state_change_event`, serait plus robuste.
- **`hvac_mode = OFF` pendant un verrou ON** : `async_set_hvac_mode(OFF)` appelle `_async_stop_heating_safe()` qui peut *refuser* l'arrêt pendant 30 min → l'entité affiche OFF alors que le relais est fermé. Défendable (protection mécanique) mais à documenter ; prévoir un arrêt d'urgence physique qui bypass la FSM.
- **Tests FSM déconnectés du code réel** : `test_fsm.py` réimplémente la FSM dans `MockDanfossFSM` au lieu de tester `climate.py` → risque de dérive silencieuse. Idem : boucle d'attente `asyncio.sleep` (2 s max) dans `sensor.py` pour attendre la plateforme climate — un coordinator éliminerait la course de setup.
- **Seuils codés en dur** : `outdoor <= 12.0` (règle A), chute fenêtre 0.4 °C/15 min, pente −1.5 °C/h, reprise +0.2 °C/h. En faire des options éviterait les faux positifs avec des sondes bruitées (une porte ouverte 5 min peut suspendre la chauffe 30 min).
- **Utilisateurs UI privés de réglages clés** : `min_cycle_duration`, `min_off_cycle_duration`, `max_cycles`, `comfort_temp`, `window_drop_threshold` ne figurent ni dans le config flow ni dans l'options flow — seul YAML permet de les changer.
- **Protection anti-gel dalle écrase la suspension fenêtre** (règle 5 après règle E) : `should_heat=True` même fenêtre ouverte. Probablement voulu, à documenter.

## 🟡 Détails et dépréciations

- `FSM_ERROR_SAFETY` déclaré dans `const.py`, jamais utilisé.
- `min_temp`/`max_temp` non exposés → l'UI propose 7–35 °C ; `DEFAULT_MIN_TEMP`/`DEFAULT_MAX_TEMP` dans `const.py` sont du code mort.
- Versions en dur : `sw_version="0.2.2"` ×2 dans `device_info`, manifest 0.2.2, mais `pyproject.toml` en 0.1.0 → dérive garantie. Lire la version du manifest.
- Imports dépréciés : `FlowResult` → `ConfigFlowResult`/`OptionsFlowResult` (2024.3+), `EVENT_HOMEASSISTANT_START` → `EVENT_HOMEASSISTANT_STARTED`.
- `ClimateEntityFeature.TURN_ON | TURN_OFF` manquants (requis depuis 2024.2 pour `climate.turn_on/off`).
- `_temp_projected` initialisé à 19.0 : `projected_error` artificiel avant la première lecture de sonde (risque atténué par la règle C) ; init à `None` plus sain.
- TODO.md annonce `content_in_root: true` dans hacs.json — faux (et c'est correct ainsi vu le layout standard).
- `_window_open`/`_window_open_time` non restaurés → reprise de chauffe possible fenêtre ouverte après redémarrage, jusqu'à re-détection.
- `_async_control_heating()` sort tôt si `hvac_mode == OFF` → pas de reset journalier des compteurs pendant une extinction longue.

## ✅ Actions recommandées (par priorité)

1. Implémenter le plafond `_max_cycles` dans `_async_start_heating_safe()` — seul verrou Danfoss manquant.
2. Réaligner les noms d'attributs de `diagnostics.py` (ou lire `extra_state_attributes`).
3. Corriger la restauration FSM (reset vers `WAITING_MIN_OFF` + resynchro du relais).
4. Exposer `min_temp`/`max_temp` et les paramètres compresseur dans l'options flow.
5. Migrer les tests FSM vers le vrai code (`pytest-homeassistant-custom-component`).
6. Nettoyage : versions depuis le manifest, imports dépréciés, `FSM_ERROR_SAFETY`, TODO.md sync.

## Conformité HACS (soumission `hacs/default`)

| Critère | État |
|---|---|
| Layout `custom_components/` | ✅ |
| `hacs.json` + manifest | ✅ |
| CI verte (hassfest, HACS, ruff, pytest) | ✅ (pytest sur mock — voir risque tests) |
| Traductions en/fr | ✅ |
| Icon / logo (`brands`) | ⚠️ manquant (requis pour le répertoire par défaut) |
| Soak test 48 h en mode shadow | ⏳ à faire |