# Revue de code — pwm-floor-heating-thermostat

**Dépôt :** https://github.com/nitrogene/pwm-floor-heating-thermostat
**Version analysée :** `manifest.json` → 0.2.2 (branche `main`)
**Périmètre :** README, `const.py`, `__init__.py`, `config_flow.py`, `manifest.json`, `climate.py` *(partiellement lisible : méthodes `_update_trajectory_projection`, setters et `extra_state_attributes` tronqués — signalé quand pertinent)*
**Date :** 2026-11-08

---

## 1. Synthèse

Travail solide : modélisation thermodynamique sérieuse (θ, τ, quota journalier en kWh), FSM de protection compresseur propre, `RestoreEntity` bien pensé, options flow complet, documentation exceptionnelle. Les points ci-dessous sont classés par gravité. Les diff proposés sont indicatifs et à adapter à la partie du fichier non relue.

---

## 2. Bugs (à corriger en priorité)

### 🔴 B1 — Le mode OFF ne coupe pas physiquement le chauffage

Dans `_async_control_heating`, la sortie précoce empêche toute commande d'arrêt :

```python
if self._hvac_mode == HVACMode.OFF:
    return
```

Si le compresseur tourne quand l'utilisateur éteint le thermostat, le relais reste enclenché indéfiniment.

**Correctif proposé :**

```diff
     async def _async_control_heating(self, now: datetime | None = None) -> None:
         """Cœur algorithmique : Bilan thermodynamique et commande par modèle."""
         if self._hvac_mode == HVACMode.OFF:
+            # Toujours tenter un arrêt propre (respecte le min-cycle en cours,
+            # ou bascule la FSM vers l'attente d'égalisation des pressions).
+            await self._async_stop_heating_safe()
+            self.async_write_ha_state()
             return
```

Et dans `async_set_hvac_mode` (à adapter selon l'implémentation réelle, non visible dans la partie relue) :

```diff
     async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
         self._hvac_mode = hvac_mode
         if hvac_mode == HVACMode.OFF:
+            # Arrêt demandé explicitement : ne pas attendre la prochaine minute.
             await self._async_stop_heating_safe()
+        else:
+            await self._async_control_heating()
-        await self._async_control_heating()
         self.async_write_ha_state()
```

> ⚠️ Discuter du comportement souhaité : un arrêt OFF doit-il respecter les 30 min de marche minimale (protection compresseur) ou couper immédiatement ? Recommandation : respecter la FSM pour la marche, mais en OFF forcer le non-redémarrage (déjà garanti par le `return`).

### 🔴 B2 — `max_cycles_per_day` n'est jamais appliqué

`self._max_cycles` est lu et `_cycles_today` est incrémenté dans `_async_start_heating_safe`, mais aucune règle n'inhibe le démarrage. Le README promet « ≤ 6 cycles/day ».

**Correctif proposé :**

```diff
     async def _async_start_heating_safe(self) -> None:
         """Démarre le compresseur si les conditions de repos minimal sont satisfaites."""
         now = dt_util.utcnow()

+        if self._cycles_today >= self._max_cycles:
+            _LOGGER.info(
+                "Démarrage refusé : budget journalier de cycles épuisé "
+                "(%d / %d). Prochain décompte à minuit local.",
+                self._cycles_today,
+                self._max_cycles,
+            )
+            self._decision_reason = (
+                f"Daily cycle budget exhausted ({self._cycles_today}/{self._max_cycles}). "
+                "Next budget at midnight."
+            )
+            return
+
         if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
             return
```

> Exception à envisager : la protection hors-gel plancher (`floor_temp <= min_floor_temp`) devrait probablement ignorer ce plafond.

### 🟠 B3 — Compteur de cycles restauré sans datation

`_last_day_reset` est réinitialisé à la date du jour dans `__init__`, mais `_cycles_today` restauré depuis les attributs peut dater d'hier : après un reboot matinal, les cycles d'hier comptent pour aujourd'hui (fausse le garde-fou B2 une fois celui-ci implémenté).

**Correctif proposé — persister la date du compteur :**

```diff
             old_attrs = old_state.attributes
             self._fsm_state = old_attrs.get("fsm_state", FSM_IDLE)
-            self._cycles_today = old_attrs.get("compressor_cycles_today", 0)
+            saved_date = old_attrs.get("counters_date")
+            if saved_date == str(dt_util.now().date()):
+                self._cycles_today = old_attrs.get("compressor_cycles_today", 0)
+                self._hours_run_today = old_attrs.get("heating_hours_done_today", 0.0)
+            else:
+                # Compteurs d'un jour précédent : repartir de zéro.
+                self._cycles_today = 0
+                self._hours_run_today = 0.0
             self._hours_run_today = old_attrs.get("heating_hours_done_today", 0.0)
```

Et exposer la date dans `extra_state_attributes` (partie non relue — à adapter) :

```diff
         attributes = {
             ...
             "compressor_cycles_today": self._cycles_today,
+            "counters_date": str(dt_util.now().date()),
             "heating_hours_done_today": round(self._hours_run_today, 2),
         }
```

### 🟠 B4 — Pas de validation `heater` requis quand `dry_run=False`

Le config flow rend l'actionneur optionnel. En mode live sans heater, l'entité passe en `HEATING` et incrémente les compteurs sans rien commander.

**Correctif proposé dans `config_flow.py` :**

```diff
             if not target_sensor:
                 errors[CONF_TARGET_SENSOR] = "missing_target_sensor"
             if not outdoor_sensor:
                 errors[CONF_OUTDOOR_SENSOR] = "missing_outdoor_sensor"
+            if not user_input.get(CONF_DRY_RUN) and not user_input.get(CONF_HEATER):
+                errors[CONF_HEATER] = "heater_required_unless_dry_run"

             if not errors:
```

(plus la clé `"heater_required_unless_dry_run"` dans `strings.json` / `translations/`.)

### 🟠 B5 — Appels de service sans `try/except`

Dans `_async_start_heating_safe` / `_async_stop_heating_safe`, un switch `unavailable` fait propaguer l'exception hors du callback timer. Le FSM n'est pas corrompu (l'exception survient avant sa mise à jour), mais le diagnostic est mauvais et `blocking=True` dans une boucle périodique est à éviter.

**Correctif proposé :**

```diff
         else:
             if self._heater_entity:
                 domain = self._heater_entity.split(".")[0]
-                _LOGGER.info("Démarrage physique compresseur : %s", self._heater_entity)
-                await self.hass.services.async_call(
-                    domain, "turn_on", {"entity_id": self._heater_entity}, blocking=True
-                )
+                try:
+                    _LOGGER.info("Démarrage physique compresseur : %s", self._heater_entity)
+                    await self.hass.services.async_call(
+                        domain, "turn_on", {"entity_id": self._heater_entity}, blocking=False
+                    )
+                except Exception as err:  # noqa: BLE001 - service indisponible, etc.
+                    _LOGGER.error("Échec de l'appel turn_on sur %s : %s", self._heater_entity, err)
+                    return  # Ne pas valider le démarrage côté FSM
```

(même traitement symétrique pour `turn_off`.)

---

## 3. Robustesse

- **R1 — Resync de l'état réel du heater au démarrage.** Après un reboot, l'entité peut croire chauffer (`running_min_lock` restauré) alors que le relais physique a changé d'état hors de HA. Lire l'état de `self._heater_entity` dans `_async_startup` (comme déjà fait via `observed_heater`) et réconcilier `_hvac_action`/`_simulated_heater_state`.
- **R2 — Détection de fenêtre agressive.** La branche `self._temp_derivative <= -1.5 and drop >= 0.2` peut suspendre la chauffe lors d'une chute rapide en plein hiver (maison peu isolée), précisément quand la chauffe est nécessaire — et `window_detection` est activé par défaut. Suggestions : exiger le capteur de contact pour cette branche, ou ne suspendre qu'en dehors des périodes de forte demande (projected_error > 0).
- **R3 — Historiques non bornés (à vérifier).** `_temp_history` et `_projection_history` : confirmer le trim (recommandé : 24 h max pour l'un, θ + marge pour l'autre). Non vérifiable sur la partie relue.
- **R4 — Magic numbers.** Les seuils `-0.5`, `0.15`, `0.2`, `-0.6`, `-0.8`, `12.0` (seuil extérieur de précharge HC), `0.2 °C/h` de remontée… → constantes nommées dans `const.py` (même non configurables) : lisibilité et testabilité.
- **R5 — Mix UTC/local.** Le cœur compare des `utcnow()` entre eux (cohérent) mais le reset journalier utilise `dt_util.now().date()`. Fonctionnel aujourd'hui, fragile en relecture — homogénéiser ou commenter.

---

## 4. Conformité Home Assistant

| Point | Recommandation |
|---|---|
| `iot_class` | `local_polling` → `local_push` (piloté par événements + timer) |
| Traductions | Si libellés français en dur : prévoir `en.json` fallback + `fr.json` |
| README vs code | README décrit un flow en 3 étapes ; le code fait un `async_step_user` unique + enregistrement d'appareil — aligner la doc |
| `CONF_COMFORT_TEMP` | Lu dans `__init__` mais absent du config flow et des options — vérifier que c'est volontaire |
| HACS | Ajouter `hacs.json` ; workflow hassfest + HACS action en CI |
| Tests | Aucun dossier `tests/` vu — prioriser des tests pytest sur la FSM et la logique de quota |

---

## 5. Points forts

- FSM claire, états explicites, transitions simples à auditer — exactement ce qu'il faut pour des sécurités « non contournables ».
- `_parse_timedelta` gérant proprement le dual YAML (`timedelta`) / options flow (`int` secondes).
- Auto-calibrage passif de H : filtrage `[0.3H, 3.0H]` + moyenne glissante à 2 % — défensif et bien conçu.
- Calcul d'`_model_error` par interpolation des projections passées — méthodologie correcte.
- Alias `heures_creuses_sensor` pour la rétrocompatibilité Linky TIC.
- Documentation de qualité rare (contraintes Danfoss, DTU 65.14, mode shadow).

---

## 6. Plan d'action suggéré

1. **B1** (OFF ne coupe pas) — risque sécurité/surconsommation.
2. **B2 + B3** (plafond de cycles + datation des compteurs).
3. **B4 + B5** (validation flow + try/except sur les services).
4. **R1–R4**, conformité HA, puis tests FSM/quota.
