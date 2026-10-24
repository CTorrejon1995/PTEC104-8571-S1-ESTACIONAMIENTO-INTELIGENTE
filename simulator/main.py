import json
import os
import random
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
SPACE_COUNT = int(os.getenv("PARKING_SPACES", "8"))
INTERVAL = float(os.getenv("PUBLISH_INTERVAL_SECONDS", "3"))

client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="parking-simulator",
)

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"[SIMULATOR] Conectado a MQTT en {MQTT_HOST}:{MQTT_PORT}", flush=True)
    else:
        print(f"[SIMULATOR] Falló conexión MQTT: {reason_code}", flush=True)

client.on_connect = on_connect

while True:
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        break
    except OSError as exc:
        print(f"[SIMULATOR] Broker aún no disponible: {exc}", flush=True)
        time.sleep(2)

client.loop_start()
occupancy = {f"P{i:02d}": random.choice([True, False]) for i in range(1, SPACE_COUNT + 1)}
entry_event_probability = 0.12

try:
    while True:
        for space_id in occupancy:
            # Simula cambios de estado ocasionales entre una lectura y la siguiente.
            if random.random() < 0.08:
                occupancy[space_id] = not occupancy[space_id]

            # Un vehículo cerca produce una distancia pequeña; un puesto libre, una grande.
            distance_cm = round(
                random.uniform(8, 25) if occupancy[space_id]
                else random.uniform(60, 180), 1
            )
            message = {
                "event_id": str(uuid.uuid4()),
                "device_id": f"sim-ultrasonic-{space_id.lower()}",
                "space_id": space_id,
                "sensor_type": "ultrasonic",
                "distance_cm": distance_cm,
                "timestamp": timestamp(),
                "simulated": True,
            }
            client.publish(
                f"parking/sensors/{space_id}/distance",
                json.dumps(message),
                qos=1,
            )
            print(f"[SIMULATOR] {space_id}: distancia={distance_cm} cm", flush=True)

        if random.random() < entry_event_probability:
            event = {
                "event_id": str(uuid.uuid4()),
                "device_id": "sim-gate-ir-01",
                "sensor_type": "infrared_gate",
                "event": "vehicle_entry",
                "timestamp": timestamp(),
                "simulated": True,
            }
            client.publish("parking/gate/entry", json.dumps(event), qos=1)
            print("[SIMULATOR] Evento simulado: ingreso de vehículo", flush=True)

        time.sleep(INTERVAL)
except KeyboardInterrupt:
    pass
finally:
    client.loop_stop()
    client.disconnect()
