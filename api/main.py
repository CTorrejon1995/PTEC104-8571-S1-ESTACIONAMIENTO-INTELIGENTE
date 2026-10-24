import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException

MQTT_HOST = os.getenv('MQTT_HOST', 'mosquitto')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
DB_PATH = os.getenv('SQLITE_PATH', '/data/events.db')
CLOUD_API_URL = os.getenv('CLOUD_API_URL', '').rstrip('/')
DEVICE_TOKEN = os.getenv('DEVICE_TOKEN', '')
DEVICE_ID = os.getenv('DEVICE_ID', 'parking-demo-01')
ORG_ID = os.getenv('ORG_ID', 'demo-org')
SITE_ID = os.getenv('SITE_ID', 'demo-site')
lock = threading.RLock()
spaces = {}
summary = None
mqtt_connected = False


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('''CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, topic TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL, synced_at TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_events_pending ON events(synced_at, created_at)')


def save_event(topic, data):
    # Los estados del procesador incluyen timestamp del sensor; MQTT QoS 1 puede reenviar.
    # El identificador se deriva del contenido para que un reenvío idéntico no duplique registros.
    raw = json.dumps({'topic': topic, 'payload': data}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    event_id = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    with db_connect() as conn:
        conn.execute('INSERT OR IGNORE INTO events(event_id,topic,payload,created_at) VALUES(?,?,?,?)',
                     (event_id, topic, json.dumps(data, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return event_id


def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    mqtt_connected = reason_code == 0
    if mqtt_connected:
        client.subscribe('parking/state/+', qos=1)
        client.subscribe('parking/summary', qos=1)
        print('[API] MQTT conectado; persistiendo eventos en SQLite', flush=True)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global mqtt_connected
    mqtt_connected = False


def on_message(client, userdata, msg):
    global summary
    try:
        data = json.loads(msg.payload.decode('utf-8'))
        if not isinstance(data, dict):
            return
        # No registrar mensajes retained del broker al reconectar; siguen disponibles en memoria.
        with lock:
            if msg.topic == 'parking/summary':
                summary = data
            elif msg.topic.startswith('parking/state/'):
                space_id = msg.topic.rsplit('/', 1)[-1]
                spaces[space_id] = data
        if not msg.retain:
            save_event(msg.topic, data)
    except (ValueError, sqlite3.Error) as exc:
        print(f'[API] Error procesando MQTT: {exc}', flush=True)


def mqtt_worker(stop):
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id='parking-api')
    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    while not stop.is_set():
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60)
            client.loop_start()
            stop.wait()
            client.disconnect()
            client.loop_stop()
        except OSError as exc:
            print(f'[API] MQTT no disponible: {exc}', flush=True)
            stop.wait(3)


def sync_worker(stop):
    while not stop.is_set():
        if CLOUD_API_URL and DEVICE_TOKEN:
            try:
                with db_connect() as conn:
                    pending = conn.execute('SELECT event_id,topic,payload,created_at FROM events WHERE synced_at IS NULL ORDER BY created_at LIMIT 50').fetchall()
                for event in pending:
                    if stop.is_set():
                        break
                    body = json.dumps({'event_id': event['event_id'], 'topic': event['topic'],
                                       'payload': json.loads(event['payload']), 'created_at': event['created_at'],
                                       'device_id': DEVICE_ID, 'org_id': ORG_ID, 'site_id': SITE_ID}).encode('utf-8')
                    req = Request(CLOUD_API_URL + '/ingest', data=body, method='POST',
                                  headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + DEVICE_TOKEN})
                    with urlopen(req, timeout=12) as response:
                        if response.status not in (200, 201):
                            raise RuntimeError(f'HTTP {response.status}')
                    with db_connect() as conn:
                        conn.execute('UPDATE events SET synced_at=? WHERE event_id=?',
                                     (datetime.now(timezone.utc).isoformat(), event['event_id']))
                if pending:
                    print(f'[SYNC] Lote procesado: {len(pending)} eventos', flush=True)
            except (HTTPError, URLError, TimeoutError, OSError, sqlite3.Error, RuntimeError) as exc:
                print(f'[SYNC] Nube no disponible; eventos conservados: {exc}', flush=True)
        stop.wait(5)


@asynccontextmanager
async def lifespan(app):
    init_db()
    stop = threading.Event()
    workers = [threading.Thread(target=mqtt_worker, args=(stop,), daemon=True),
               threading.Thread(target=sync_worker, args=(stop,), daemon=True)]
    for worker in workers:
        worker.start()
    yield
    stop.set()
    for worker in workers:
        worker.join(timeout=5)


app = FastAPI(title='Estacionamiento Inteligente API', version='0.3.0', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok', 'mqtt_connected': mqtt_connected, 'timestamp': datetime.now(timezone.utc).isoformat()}


@app.get('/parking/spaces')
def get_spaces():
    with lock:
        items = [{'space_id': k, **v} for k, v in sorted(spaces.items())]
    return {'count': len(items), 'spaces': items}


@app.get('/parking/spaces/{space_id}')
def get_space(space_id: str):
    with lock:
        data = spaces.get(space_id)
    if data is None:
        raise HTTPException(404, 'Espacio no encontrado')
    return {'space_id': space_id, **data}


@app.get('/parking/summary')
def get_summary():
    with lock:
        current = dict(summary) if summary else None
    if current is None:
        raise HTTPException(503, 'Aún no se recibe el resumen MQTT')
    return current


@app.get('/parking/events')
def get_events(limit: int = 20):
    if not 1 <= limit <= 100:
        raise HTTPException(422, 'limit debe estar entre 1 y 100')
    with db_connect() as conn:
        rows = conn.execute('SELECT event_id,topic,payload,created_at,synced_at FROM events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'events': [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]}


@app.get('/parking/sync-status')
def sync_status():
    with db_connect() as conn:
        total, pending = conn.execute('SELECT COUNT(*), SUM(CASE WHEN synced_at IS NULL THEN 1 ELSE 0 END) FROM events').fetchone()
    return {'total_events': total, 'pending_events': pending or 0,
            'cloud_configured': bool(CLOUD_API_URL and DEVICE_TOKEN)}
