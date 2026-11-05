"""Tests pour le flux de configuration (Config Flow) et d'options (Options Flow)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import MockConfigEntry
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat import (
    async_reload_entry,
)
from custom_components.pwm_floor_heating_thermostat import (
    async_setup_entry as init_async_setup_entry,
)
from custom_components.pwm_floor_heating_thermostat import (
    async_unload_entry as init_async_unload_entry,
)
from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.climate import (
    async_setup_entry as climate_async_setup_entry,
)
from custom_components.pwm_floor_heating_thermostat.config_flow import (
    PwmFloorHeatingConfigFlow,
    PwmFloorHeatingOptionsFlowHandler,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    DOMAIN,
)


@pytest.mark.anyio
async def test_config_flow_shows_form():
    """Vérifie que l'étape utilisateur sans saisie affiche le formulaire."""
    flow = PwmFloorHeatingConfigFlow()
    result = await flow.async_step_user(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {}


@pytest.mark.anyio
async def test_config_flow_missing_sensors():
    """Vérifie le rejet avec erreurs si les capteurs obligatoires sont absents."""
    flow = PwmFloorHeatingConfigFlow()

    # Aucun capteur
    result = await flow.async_step_user(user_input={CONF_NAME: "Salon"})
    assert result["type"] == "form"
    assert result["errors"][CONF_TARGET_SENSOR] == "missing_target_sensor"
    assert result["errors"][CONF_OUTDOOR_SENSOR] == "missing_outdoor_sensor"

    # Capteur extérieur manquant
    result2 = await flow.async_step_user(
        user_input={
            CONF_NAME: "Salon",
            CONF_TARGET_SENSOR: "sensor.temperature_salon",
        }
    )
    assert result2["type"] == "form"
    assert CONF_TARGET_SENSOR not in result2["errors"]
    assert result2["errors"][CONF_OUTDOOR_SENSOR] == "missing_outdoor_sensor"


@pytest.mark.anyio
async def test_config_flow_success():
    """Vérifie la création réussie d'une entrée avec identifiant unique."""
    flow = PwmFloorHeatingConfigFlow()
    user_input = {
        CONF_NAME: "Salon Thermostat",
        CONF_TARGET_SENSOR: "sensor.temp_salon",
        CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
        CONF_HEATER: "switch.relais_salon",
        CONF_HEAT_LOSS: 35.0,
        CONF_POWER_WATTS: 6500.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.25,
        CONF_DRY_RUN: True,
    }

    result = await flow.async_step_user(user_input=user_input)

    assert result["type"] == "create_entry"
    assert result["title"] == "Salon Thermostat"
    assert result["data"] == user_input
    assert flow.unique_id == "sensor.temp_salon_switch.relais_salon"


@pytest.mark.anyio
async def test_config_flow_abort_if_already_configured():
    """Vérifie l'avortement si l'unique_id est déjà configuré."""
    flow = PwmFloorHeatingConfigFlow()
    flow._configured_ids.add("sensor.temp_salon_switch.relais_salon")

    user_input = {
        CONF_NAME: "Salon Thermostat",
        CONF_TARGET_SENSOR: "sensor.temp_salon",
        CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
        CONF_HEATER: "switch.relais_salon",
    }

    with pytest.raises(Exception, match="already_configured"):
        await flow.async_step_user(user_input=user_input)


@pytest.mark.anyio
async def test_options_flow_shows_form():
    """Vérifie l'affichage du formulaire d'options prérempli."""
    entry = MockConfigEntry(
        entry_id="test_entry_123",
        title="Salon Thermostat",
        data={
            CONF_NAME: "Salon Thermostat",
            CONF_TARGET_SENSOR: "sensor.temp_salon",
            CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
            CONF_HEAT_LOSS: 40.0,
            CONF_DRY_RUN: True,
        },
    )

    handler = PwmFloorHeatingConfigFlow.async_get_options_flow(entry)
    assert isinstance(handler, PwmFloorHeatingOptionsFlowHandler)

    result = await handler.async_step_init(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "init"


@pytest.mark.anyio
async def test_options_flow_update_settings():
    """Vérifie la mise à jour des options (ex: passage de Shadow Mode à Réel)."""
    entry = MockConfigEntry(
        entry_id="test_entry_123",
        title="Salon Thermostat",
        data={
            CONF_NAME: "Salon Thermostat",
            CONF_TARGET_SENSOR: "sensor.temp_salon",
            CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
            CONF_HEAT_LOSS: 40.0,
            CONF_DRY_RUN: True,
        },
    )

    handler = PwmFloorHeatingOptionsFlowHandler(entry)
    new_options = {
        CONF_DRY_RUN: False,  # Bascule en mode réel
        CONF_HEAT_LOSS: 35.0,  # Recalibrage des déperditions
        CONF_POWER_WATTS: 6500.0,
        CONF_SLAB_TIME_CONSTANT: 16.0,
        CONF_DEAD_TIME: 2.5,
    }

    result = await handler.async_step_init(user_input=new_options)
    assert result["type"] == "create_entry"
    assert result["data"] == new_options


@pytest.mark.anyio
async def test_climate_async_setup_entry():
    """Vérifie que climate.async_setup_entry instancie l'entité avec options fusionnées."""
    hass = MagicMock()
    entry = MockConfigEntry(
        entry_id="entry_456",
        title="Chambre Thermostat",
        data={
            CONF_NAME: "Chambre Thermostat",
            CONF_TARGET_SENSOR: "sensor.temp_chambre",
            CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
            CONF_HEAT_LOSS: 25.0,
            CONF_DRY_RUN: True,
        },
        options={
            CONF_HEAT_LOSS: 20.0,  # Surcharge par les options
        },
    )

    added_entities = []

    def mock_add_entities(entities):
        added_entities.extend(entities)

    await climate_async_setup_entry(hass, entry, mock_add_entities)

    assert len(added_entities) == 1
    thermostat = added_entities[0]
    assert isinstance(thermostat, PwmFloorHeatingThermostat)
    assert thermostat._heat_loss == 20.0  # Option prioritaire
    assert thermostat.unique_id == "entry_456"
    assert thermostat.name == "Chambre Thermostat"
    assert thermostat.device_info is not None


@pytest.mark.anyio
async def test_init_setup_and_unload_entry():
    """Vérifie que l'initialisation et le déchargement de l'entrée délèguent à Home Assistant."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()

    entry = MockConfigEntry(
        entry_id="entry_789",
        title="Bureau",
        data={
            CONF_NAME: "Bureau",
            CONF_TARGET_SENSOR: "sensor.temp_bureau",
            CONF_OUTDOOR_SENSOR: "sensor.temp_ext",
        },
    )

    # Setup entry
    setup_result = await init_async_setup_entry(hass, entry)
    assert setup_result is True
    assert DOMAIN in hass.data
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    # Reload entry
    await async_reload_entry(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("entry_789")

    # Unload entry
    unload_result = await init_async_unload_entry(hass, entry)
    assert unload_result is True
    hass.config_entries.async_unload_platforms.assert_awaited_once()
