import json
import os
import secrets
from functools import lru_cache
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI(title='Parking Cloud Ingestion API', version='0.1.0', docs_url=None, redoc_url=None)


class Event(BaseModel):
    event_id: str = Field(min_length=64, max_length=64, pattern=r'^[a-f0-9]{64}$')
    topic: str = Field(min_length=1, max_length=120)
    payload: dict
    created_at: str
    device_id: str
    org_id: str
    site_id: str


@lru_cache(maxsize=1)
def get_db():
    raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if not raw:
        raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON no configurada')
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
    return firestore.client()


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/ingest')
def ingest(event: Event, authorization: str | None = Header(default=None)):
    token = os.getenv('DEVICE_TOKEN')
    if not token or not authorization or not authorization.startswith('Bearer ') or not secrets.compare_digest(authorization[7:], token):
        raise HTTPException(401, 'Token de dispositivo inválido')
    expected_device = os.getenv('DEVICE_ID', 'parking-demo-01')
    expected_org = os.getenv('ORG_ID', 'demo-org')
    expected_site = os.getenv('SITE_ID', 'demo-site')
    if (event.device_id, event.org_id, event.site_id) != (expected_device, expected_org, expected_site):
        raise HTTPException(403, 'Dispositivo o sitio no autorizado')
    allowed_topic = (
        event.topic == 'parking/summary'
        or (event.topic.startswith('parking/state/') and len(event.topic.split('/')) == 3 and bool(event.topic.split('/')[2]))
        or (event.topic.startswith('parking/pir/') and len(event.topic.split('/')) == 4 and bool(event.topic.split('/')[2]) and event.topic.endswith('/event'))
    )
    if not allowed_topic:
        raise HTTPException(422, 'Tópico no permitido')
    doc = get_db().collection('organizations').document(expected_org).collection('sites').document(expected_site).collection('events').document(event.event_id)
    try:
        doc.create(event.model_dump())
        return {'status': 'created', 'event_id': event.event_id}
    except Exception as exc:
        from google.api_core.exceptions import AlreadyExists
        if isinstance(exc, AlreadyExists):
            return {'status': 'already_exists', 'event_id': event.event_id}
        raise
