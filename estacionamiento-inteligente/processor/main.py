import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
OCCUPIED_THRESHOLD_CM = float(os.getenv("OCCUPIED_DISTANCE_CM", "30"))

latest_spaces = {}
entry_count = 0

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("[PROCESSOR] Conectado a MQTT; suscribiendo tópicos...", flush=True)
        client.subscribe("parking/sensors/+/distance", qos=1)
        client.subscribe("parking/gate/entry", qos=1)
    else:
        print(f"[PROCESSOR] Error de conexión MQTT: {reason_code}", flush=True)

def on_message(client, userdata, msg):
    global entry_count
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(f"[PROCESSOR] Mensaje inválido en {msg.topic}", flush=True)
        return

    if msg.topic == "parking/gate/entry":
        entry_count += 1
        print(f"[PROCESSOR] 🚘 Ingreso #{entry_count} registrado. Evento={payload.get('event_id')}", flush=True)
        publish_summary(client)
        return

    space_id = payload.get("space_id")
    distance = payload.get("distance_cm")
    if not space_id or not isinstance(distance, (int, float)):
        print(f"[PROCESSOR] Lectura sin space_id/distancia válida: {payload}", flush=True)
        return

    occupied = distance <= OCCUPIED_THRESHOLD_CM
    previous = latest_spaces.get(space_id, {}).get("occupied")
    latest_spaces[space_id] = {
        "occupied": occupied,
        "distance_cm": distance,
        "timestamp": payload.get("timestamp"),
        "event_id": payload.get("event_id"),
    }
    state = "OCUPADO" if occupied else "LIBRE"
    changed = " (cambio)" if previous is not None and previous != occupied else ""
    print(f"[PROCESSOR] {space_id}: {state} ({distance} cm){changed}", flush=True)

    client.publish(
        f"parking/state/{space_id}",
        json.dumps({
            "space_id": space_id,
            "occupied": occupied,
            "distance_cm": distance,
            "timestamp": payload.get("timestamp"),
            "simulated": payload.get("simulated", True),
        }),
        qos=1,
        retain=True,
    )
    publish_summary(client)

def publish_summary(client):
    occupied = sum(1 for value in latest_spaces.values() if value["occupied"])
    total = len(latest_spaces)
    summary = {
        "total_spaces_seen": total,
        "occupied_spaces": occupied,
        "free_spaces": max(total - occupied, 0),
        "occupancy_percent": round(occupied / total * 100, 1) if total else 0,
        "vehicle_entries": entry_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "simulated": True,
    }
    client.publish("parking/summary", json.dumps(summary), qos=1, retain=True)
    print(
        f"[SUMMARY] ocupados={occupied}, libres={max(total-occupied, 0)}, "
        f"ocupación={summary['occupancy_percent']}%, ingresos={entry_count}",
        flush=True,
    )

client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="parking-processor",
)
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        break
    except OSError as exc:
        print(f"[PROCESSOR] Broker aún no disponible: {exc}", flush=True)
        time.sleep(2)

client.loop_forever()
