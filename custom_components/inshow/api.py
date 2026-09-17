import logging
import random
import ssl
import string
import json
from datetime import timedelta

import aiohttp
import paho.mqtt.client as mqtt
import asyncio
from korean_romanizer.romanizer import Romanizer

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

TOKEN_REFRESH_INTERVAL = timedelta(hours=1)


class CannotConnect(Exception):
    """Error to indicate we cannot connect to the Inshow API."""


class InvalidAuth(Exception):
    """Error to indicate invalid Inshow credentials."""


class InshowApi:
    def __init__(self, hass, client_id, client_pw):
        self.hass = hass
        self._LOGGER = logging.getLogger(__name__)
        self.token = None
        self.base_url = "https://iot.interiorshow.kr/api"
        self.client_id = client_id
        self.client_pw = client_pw
        self.data = None
        self.client = None
        self._unsub_token_refresh = None

    async def login(self):
        """Authenticate against the Inshow API and store the access token.

        Raises CannotConnect or InvalidAuth on failure.
        """
        url = f"{self.base_url}/authorize/signIn"
        data = {"type": "e", "email": self.client_id, "password": self.client_pw}
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(url, data=data) as response:
                if response.status != 200:
                    raise CannotConnect(f"Unexpected status code {response.status}")
                response_data = await response.json()
        except aiohttp.ClientError as err:
            raise CannotConnect from err

        result_data = response_data.get("resultData") or {}
        token = result_data.get("accessToken")
        if not token:
            raise InvalidAuth("No access token in response")

        self.token = token
        self._LOGGER.debug("Access token received")
        return token

    async def _async_refresh_token(self, now=None):
        """Periodically refresh the access token."""
        try:
            await self.login()
        except (CannotConnect, InvalidAuth) as err:
            self._LOGGER.error("Failed to refresh access token: %s", err)

    async def initialize(self):
        await self.login()

        self._unsub_token_refresh = async_track_time_interval(
            self.hass, self._async_refresh_token, TOKEN_REFRESH_INTERVAL
        )

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._LOGGER.info("Connected to MQTT broker successfully")
            else:
                self._LOGGER.error("Failed to connect, return code %s", rc)

        def on_message(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                if 'serial' in data:
                    self.hass.loop.call_soon_threadsafe(
                        async_dispatcher_send, self.hass, "inshow_light_update", data
                    )
                else:
                    data['controllerId'] = msg.topic.split('/')[2]
                    self.hass.loop.call_soon_threadsafe(
                    async_dispatcher_send, self.hass, "inshow_climate_update", data
                    )
                self._LOGGER.debug("Received message '%s' on topic '%s'", data, msg.topic)
            except Exception as e:
                self._LOGGER.error("Error in on_message: %s", e)

        def on_disconnect(client, userdata, rc):
            self._LOGGER.warning("Disconnected with result code %s", rc)

        base_client_id = "inshow_mobile"
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        client_id = f"{base_client_id}_{random_suffix}"

        self.client = mqtt.Client(client_id=client_id, transport="websockets")

        # SSL 설정
        await asyncio.to_thread(self.client.tls_set, cert_reqs=ssl.CERT_NONE)
        await asyncio.to_thread(self.client.tls_insecure_set, True)

        # WebSocket 연결 설정
        self.client.ws_set_options(path="/ws")

        # 콜백 함수 등록
        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.on_disconnect = on_disconnect

        # MQTT 브로커에 연결
        broker_host = "iot.interiorshow.kr"
        broker_port = 443
        await asyncio.to_thread(self.client.connect, broker_host, broker_port, 60)

        self.client.loop_start()

    async def get_data(self):
        if not self.token:
            self._LOGGER.error("No access token available.")
            return None

        headers = {"Authorization": f"Bearer {self.token}"}
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self.base_url}/zones", headers=headers
            ) as response:
                datas = await response.json()
                datas = datas.get("resultData")

                controller = set()
                entityData = {}
                ids = []
                for data in datas:
                    ids.append(data.get("_id"))
                    for x in data["groups"]:
                        prefix = Romanizer(x["name"]).romanize() + "_"
                        for y in x["devices"]:
                            if not y["isVirtual"]:
                                name = prefix + y["name"].replace("번", "")
                                entityData[name] = {
                                    "pri_name": Romanizer(
                                        data.get("name")
                                    ).romanize(),
                                    "id": y["_id"],
                                    "controllerId": y["controllerId"],
                                    "item": y["item"],
                                }
                                controller.add(y["controllerId"])
                self.data = entityData
                for id in ids:
                    self.mqtt_subscribe(f"$MTZ/inshow/zone/{id}/state/control")
                for subs in controller:
                    self.mqtt_subscribe(f"$MTZ/inshow/mcs/{subs}/state/changed")
                    if subs.startswith("75DFISCA"):
                        self.mqtt_subscribe(f"stat/inshow/{subs}/#")
                return True
        except Exception as e:
            self._LOGGER.error("Error during data retrieval: %s", e)
            return False

    def request_data(self, name):
        return self.data[name]

    def request_keys_for_light(self):
        return [key for key in self.data.keys() if "75DFISCA" not in key]

    def request_keys_for_climate(self):
        return [key for key in self.data.keys() if "75DFISCA" in key]

    def mqtt_subscribe(self, topic):
        self.client.subscribe(topic)

    def mqtt_msg(self, topic, msg):
        """Publish an MQTT message."""
        self._LOGGER.debug("MQTT MSG: %s", msg)
        self.client.publish(topic=topic, payload=msg)

    def shutdown(self):
        """Stop background tasks started by this API instance."""
        if self._unsub_token_refresh is not None:
            self._unsub_token_refresh()
            self._unsub_token_refresh = None
