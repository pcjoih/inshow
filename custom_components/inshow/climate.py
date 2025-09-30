from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from . import DOMAIN
import logging
import json

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_SCALE = (0, 100)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Inshow Climate entities from config entry."""

    # config_entry.runtime_data에 저장된 InshowApi 객체를 가져옴
    api = config_entry.runtime_data

    # api에서 모든 엔티티 키를 가져옴 (request_keys 메서드를 사용)
    keys = api.request_keys_for_climate()

    # 엔티티 목록을 만들어서 추가
    climates = [InshowClimate(api, key) for key in keys]

    # Home Assistant에 엔티티 추가
    async_add_entities(climates)

class InshowClimate(ClimateEntity):
    def __init__(self, api, name):
        # API 데이터에서 초기 상태와 밝기 정보를 설정        
        self._api = api
        self._name = name
        self._data = api.request_data(name)
        self._cId = self._data.get("controllerId")
        self._pri_name = self._data.get("pri_name")
        self._id = self._data.get("id")
        self._current_temp = float(self._data.get("item").get("currentTemp"))
        self._target_temp = float(self._data.get("item").get("targetTemp"))
        self._onoff = self._data.get("item").get("onoff") == 1
        self._pattern = self._data.get("item").get("pattern")

    @property
    def name(self):
        return self._name

    @property
    def current_temperature(self):
        return self._current_temp

    @property
    def target_temperature(self):
        return self._target_temp
    
    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS
    
    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self._onoff else HVACMode.OFF
    
    @property
    def hvac_modes(self):
        return [HVACMode.OFF, HVACMode.HEAT]
    
    @property
    def preset_modes(self):
        return ["1", "2", "3", "4", "5"]
    
    @property
    def preset_mode(self):
        return self._pattern
    
    @property
    def min_temp(self):
        return 9.0
    
    @property
    def supported_features(self):
        """Return the list of supported features."""
        return ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    
    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._onoff = True
        elif hvac_mode == HVACMode.OFF:
            self._onoff = False
        await self._update_state("AwayModeSet")

    async def async_turn_on(self, **kwargs):
        """Turn the climate on."""
        self._onoff = True

        # 온도 값이 전달되었는지 확인하고 처리
        if "TempTargetSet" in kwargs:            
            self._target_temp = float(kwargs["TempTargetSet"])

        if "PatternModeSet" in kwargs:
            self._pattern = kwargs["PatternModeSet"]

        await self._update_state("AwayModeSet")

    async def async_turn_off(self, **kwargs):
        """Turn the climate off."""
        self._onoff = False

        await self._update_state("AwayModeSet")

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if "temperature" in kwargs:
            self._target_temp = float(kwargs["temperature"])
            await self._update_state("TempTargetSet")

    async def async_set_preset_mode(self, preset_mode):
        """Set new preset mode."""
        self._pattern = preset_mode
        await self._update_state("PatternModeSet")

    async def _update_state(self, command):
        """Update the state and send an MQTT message."""
        await self._send_mqtt_message(command)
        self.async_write_ha_state()

    async def _send_mqtt_message(self, command):
        """Helper function to send an MQTT message."""
        if self._api is None:
            _LOGGER.error("API is not initialized")
            return
        command_line = {"AwayModeSet": "AWAYMODESET", 
                        "TempTargetSet": "TEMPTARGETSET", 
                        "PatternModeSet": "PATTERNMODESET"}
        if "AwayModeSet" == command:
            payload = {command: 0 if self._onoff else 1}
        elif "TempTargetSet" == command:
            payload = {command: self._target_temp}
        elif "PatternModeSet" == command:
            payload = {command: int(self._pattern)}
        topic = f"stat/inshow/{self._cId}/{command_line[command]}"
        # MQTT 메시지 발행
        self._api.mqtt_msg(topic, json.dumps(payload))

    @property
    def device_info(self):
        """Return device information for this entity."""
        return {
            "identifiers": {(DOMAIN, "IOT")},  # 고유 장치 식별자
            "name": "Inshow",  # 장치 이름
            "manufacturer": "Inshow",  # 제조사 이름
            "model": "Inshow Climate Model",  # 모델 이름
            "sw_version": "1.0",  # 소프트웨어 버전
        }

    @property
    def unique_id(self):
        """Return a unique ID for this climate entity."""
        return f"{self._name}_{self._cId}"

    async def async_added_to_hass(self):
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, "inshow_climate_update", self._handle_climate_update
        )

    async def _handle_climate_update(self, event_data):
        """Handle the incoming MQTT message and update the climate entity."""

        # MQTT 메시지에서 port 정보를 처리
        # Received message '{'Temperature': 25.5, 'POWER_RL': 'OFF'}' on topic 'stat/inshow/75DFISCA6310/ROOMTEMPREAL'
        # Received message '{'AwayModeSet': 0}' on topic 'stat/inshow/75DFISCA602E/AWAYMODESET'
        # Received message '{'TempTargetSet': 23.0}' on topic 'stat/inshow/75DFISCA602E/TEMPTARGETSET'
        # Received message '{'PatternModeSet': 1}' on topic 'stat/inshow/75DFISCA602E/PATTERNMODESET'
        if event_data.get("controllerId") == self._cId:
            if 'Temperature' in event_data:
                self._current_temp = float(event_data.get("Temperature", self._current_temp))
                self._onoff = event_data.get("POWER_RL", "OFF") == "ON"
            if 'AwayModeSet' in event_data:
                self._onoff = event_data.get("AwayModeSet", 0) == 0
            if 'TempTargetSet' in event_data:
                self._target_temp = float(event_data.get("TempTargetSet", self._target_temp))
            if 'PatternModeSet' in event_data:
                self._pattern = event_data.get("PatternModeSet", self._pattern)     
            # 상태 변경 알림
            self.async_write_ha_state()
        else:
            return

    async def async_will_remove_from_hass(self):
        # Dispatcher unsubscribe
        if self._unsub_dispatcher is not None:
            self._unsub_dispatcher()
