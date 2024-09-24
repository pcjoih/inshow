from homeassistant.components.light import LightEntity, COLOR_MODE_COLOR_TEMP
from . import DOMAIN
import logging
from homeassistant.util.color import value_to_brightness
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import json

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_SCALE = (0, 100)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Inshow light entities from config entry."""

    # config_entry.runtime_data에 저장된 InshowApi 객체를 가져옴
    api = config_entry.runtime_data

    # api에서 모든 엔티티 키를 가져옴 (request_keys 메서드를 사용)
    keys = api.request_keys()

    # 엔티티 목록을 만들어서 추가
    lights = [InshowLight(api, key) for key in keys]

    # Home Assistant에 엔티티 추가
    async_add_entities(lights)


class InshowLight(LightEntity):
    def __init__(self, api, name):
        # API 데이터에서 초기 상태와 밝기 정보를 설정
        self._api = api
        self._name = name
        self._data = api.request_data(name)
        self._cId = self._data.get("controllerId")
        self._pri_name = self._data.get("pri_name")
        self._id = self._data.get("id")
        self._port = self._data.get("item").get("ports")[0]
        self._bright = self._data.get("item").get("bright")
        self._color = self._data.get("item").get("color")
        self._state = self._data.get("item").get("onoff") == 1
        self._color_mode = COLOR_MODE_COLOR_TEMP
        self.should_poll = False
        self._max_color_temp_kelvin = 5500
        self._min_color_temp_kelvin = 3500

    @property
    def name(self):
        return self._name

    @property
    def is_on(self):
        return self._state

    async def async_turn_on(self, **kwargs):
        """Turn the light on."""
        self._state = True

        # 밝기 값이 전달되었는지 확인하고 처리
        if "brightness" in kwargs:
            # 0~255 범위의 값을 0~100으로 변환
            brightness_ha = kwargs["brightness"]
            self._bright = int((brightness_ha / 255) * 100)

        # 색 온도 값이 전달되었는지 확인하고 처리
        if "color_temp_kelvin" in kwargs:
            color_temp = kwargs["color_temp_kelvin"]
            # 3500K ~ 5500K를 0~20 값으로 변환
            self._color = int(((color_temp - 3500) / 2000) * 20)

        await self._update_state()

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        self._state = False

        await self._update_state()

    async def _update_state(self):
        """Update the state and send an MQTT message."""
        await self._send_mqtt_message()
        self.async_write_ha_state()

    def scale_bright(self):
        return int(self._bright // 10) * 10

    def scale_color(self):
        return int(self._color // 2) * 2

    async def _send_mqtt_message(self):
        """Helper function to send an MQTT message."""
        if self._api is None:
            _LOGGER.error("API is not initialized")
            return
        payload = {
            "cmd": "c",
            "serial": self._cId,
            "type": 1,
            "data": {
                "ports": [self._port] if self._port else [],
                "onoff": 1 if self._state else 0,
                "bright": self.scale_bright(),
                "color": self.scale_color(),
            },
        }
        topic = f"$MTZ/inshow/mcs/{self._cId}/state/control"
        # MQTT 메시지 발행
        self._api.mqtt_msg(topic, json.dumps(payload))

    @property
    def brightness(self):
        """Return the current brightness."""
        return value_to_brightness(BRIGHTNESS_SCALE, self._bright)

    @property
    def color_temp_kelvin(self):
        return int((self._color / 20) * 2000 + 3500)

    @property
    def supported_color_modes(self):
        """Return the supported color modes."""
        return {COLOR_MODE_COLOR_TEMP}

    @property
    def color_mode(self):
        """Return the current color mode."""
        return self._color_mode

    @property
    def max_color_temp_kelvin(self):
        return self._max_color_temp_kelvin

    @property
    def min_color_temp_kelvin(self):
        return self._min_color_temp_kelvin

    @property
    def device_info(self):
        """Return device information for this entity."""
        return {
            "identifiers": {(DOMAIN, "IOT")},  # 고유 장치 식별자
            "name": "Inshow",  # 장치 이름
            "manufacturer": "Inshow",  # 제조사 이름
            "model": "Inshow Light Model",  # 모델 이름
            "sw_version": "1.0",  # 소프트웨어 버전
        }

    @property
    def unique_id(self):
        """Return a unique ID for this light."""
        return f"{self._name}_{self._cId}_{self._port}"

    async def async_added_to_hass(self):
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, "inshow_light_update", self._handle_light_update
        )

    async def _handle_light_update(self, event_data):
        """Handle the incoming MQTT message and update the light entity."""

        # MQTT 메시지에서 port 정보를 처리
        data = event_data.get("data", {})
        ports = data.get("ports", [])
        port = data.get("port", ports[0] if ports else None)

        # 조건: serial이 일치하고 port가 일치하는 경우에만 상태 변경
        if event_data.get("serial") == self._cId and port == self._port:
            # 상태 업데이트
            self._state = data.get("onoff", self._state) == 1
            self._bright = data.get("bright", self._bright)
            self._color = data.get("color", self._color)

            # 상태 변경 알림
            self.async_write_ha_state()
        else:
            return

    async def async_will_remove_from_hass(self):
        # Dispatcher unsubscribe
        if self._unsub_dispatcher is not None:
            self._unsub_dispatcher()
