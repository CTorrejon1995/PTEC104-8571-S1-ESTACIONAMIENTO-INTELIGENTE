#!/usr/bin/env python3
"""Registro PIR HC-SR501 en CSV y publicación de eventos MQTT.

OUT -> GPIO17 (pin físico 11), VCC -> 5 V, GND -> GND.
Ejecutar en Raspberry Pi: python3 estacionamientoF_mqtt.py
CSV: ~/registros_pir.csv
"""
import csv
import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from signal import pause

from gpiozero import DigitalInputDevice
import paho.mqtt.publish as publish

PIN_PIR = 17
CALIBRACION_S = 30
COOLDOWN_S = 5
ARCHIVO = os.path.expanduser('~/registros_pir.csv')
CAMPOS = ['fecha', 'hora', 'evento', 'duracion_s', 'total_detecciones']
MQTT_HOST = os.getenv('MQTT_HOST', '127.0.0.1')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
DEVICE_ID = 'pir-entrada-01'
TOPIC = f'parking/pir/{DEVICE_ID}/event'

estado = {'inicio_mov': None, 'ultimo_conteo': 0.0, 'total': 0}
t_arranque = time.monotonic()
pendientes = queue.Queue(maxsize=500)


def publicar_en_segundo_plano():
    while True:
        mensaje = pendientes.get()
        try:
            publish.single(TOPIC, payload=json.dumps(mensaje), hostname=MQTT_HOST,
                           port=MQTT_PORT, qos=1, retain=False)
            print(f"[MQTT] Publicado: {mensaje['event']} ({mensaje['event_id']})", flush=True)
        except Exception as exc:
            print(f'[MQTT] Error al publicar: {exc}. Evento conservado en CSV.', flush=True)
        finally:
            pendientes.task_done()


def registrar(evento, duracion=''):
    ahora = datetime.now()
    fila = {
        'fecha': ahora.strftime('%Y-%m-%d'),
        'hora': ahora.strftime('%H:%M:%S'),
        'evento': evento,
        'duracion_s': duracion,
        'total_detecciones': estado['total'],
    }
    es_nuevo = not os.path.exists(ARCHIVO) or os.path.getsize(ARCHIVO) == 0
    with open(ARCHIVO, 'a', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS)
        if es_nuevo:
            escritor.writeheader()
        escritor.writerow(fila)
    print(f"{fila['fecha']} {fila['hora']} {evento} (total: {estado['total']})"
          + (f' duracion: {duracion} s' if duracion != '' else ''), flush=True)

    mensaje = {
        'event_id': str(uuid.uuid4()),
        'device_id': DEVICE_ID,
        'sensor_type': 'pir',
        'event': evento,
        'duration_s': duracion if duracion != '' else None,
        'total_detecciones': estado['total'],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'simulated': False,
    }
    try:
        pendientes.put_nowait(mensaje)
    except queue.Full:
        print('[MQTT] Cola llena. Evento conservado solo en CSV.', flush=True)


def al_activarse():
    if time.monotonic() - t_arranque < CALIBRACION_S:
        return
    ahora = time.monotonic()
    estado['inicio_mov'] = ahora
    if ahora - estado['ultimo_conteo'] >= COOLDOWN_S:
        estado['total'] += 1
        estado['ultimo_conteo'] = ahora
    registrar('movimiento')


def al_desactivarse():
    if estado['inicio_mov'] is None:
        return
    duracion = round(time.monotonic() - estado['inicio_mov'], 1)
    estado['inicio_mov'] = None
    registrar('fin_movimiento', duracion)


def main():
    threading.Thread(target=publicar_en_segundo_plano, daemon=True).start()
    pir = DigitalInputDevice(PIN_PIR, pull_up=False)
    pir.when_activated = al_activarse
    pir.when_deactivated = al_desactivarse
    print(f'Calibrando {CALIBRACION_S} s. No te muevas frente al sensor...', flush=True)
    time.sleep(CALIBRACION_S)
    print(f'Listo. Guardando en {ARCHIVO} y publicando en {TOPIC}. Ctrl+C para salir.', flush=True)
    try:
        pause()
    except KeyboardInterrupt:
        print('\nPrograma detenido.', flush=True)
    finally:
        pir.close()


if __name__ == '__main__':
    main()
