"""Forward Pilot 2 aircraft OSD from an existing authenticated MQTT broker."""
import json
import logging
import os
import re
import ssl
from urllib.error import URLError
from urllib.request import Request, urlopen

log = logging.getLogger('wall_dji_bridge')


def parse_osd(payload):
    envelope = json.loads(payload)
    fields = envelope['data']
    return {
        'latitude': fields.get('latitude'),
        'longitude': fields.get('longitude'),
        'elevation': fields.get('elevation'),
        'horizontal_speed': fields.get('horizontal_speed'),
        'timestamp': envelope.get('timestamp'),
    }


def main():
    import paho.mqtt.client as mqtt

    base = os.environ['UAV_WALL_BRIDGE_API'].rstrip('/')
    token = os.environ['UAV_WALL_TELEMETRY_KEY']
    configured = json.loads(os.environ['UAV_WALL_DJI_SERIALS'])
    if not configured or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', value)
                             for value in (*configured, *configured.values())):
        raise ValueError('UAV_WALL_DJI_SERIALS must map aircraft serials to device IDs')
    routes = {f'thing/product/{serial}/osd': f'{base}/live/{device}/telemetry'
              for serial, device in configured.items()}
    broker = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    broker.username_pw_set(os.environ['UAV_WALL_MQTT_USER'], os.environ['UAV_WALL_MQTT_PASSWORD'])
    broker.tls_set_context(ssl.create_default_context(cafile=os.getenv('UAV_WALL_MQTT_CA') or None))

    def connect(client, _data, _flags, reason, _properties):
        if reason.is_failure:
            log.error('MQTT connection rejected: %s', reason)
            return
        client.subscribe([(topic, 0) for topic in routes])
        log.info('Subscribed to %d aircraft', len(routes))

    def message(_client, _data, packet):
        if packet.topic not in routes or packet.retain or len(packet.payload) > 65536:
            return
        try:
            body = json.dumps(parse_osd(packet.payload), allow_nan=False).encode()
            request = Request(routes[packet.topic], method='PUT', data=body,
                              headers={'Content-Type': 'application/json', 'X-Wall-Telemetry-Key': token})
            with urlopen(request, timeout=2):
                pass
        except (URLError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning('OSD relay failed: %s', type(exc).__name__)

    broker.on_connect = connect
    broker.on_message = message
    broker.reconnect_delay_set(1, 20)
    broker.connect_async(os.environ['UAV_WALL_MQTT_HOST'], int(os.getenv('UAV_WALL_MQTT_PORT', '8883')))
    broker.loop_forever(retry_first_connection=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
