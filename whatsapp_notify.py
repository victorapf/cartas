import base64
import io
import logging
import os
import threading
import time

import segno
from neonize.client import NewClient
from neonize.events import ConnectedEv

log = logging.getLogger('cartas.whatsapp')
logging.getLogger('neonize').setLevel(logging.WARNING)

SENDER = os.environ.get('WA_SENDER', '584244148836')
RECIPIENT = os.environ.get('WA_RECIPIENT', '584141438927')
SESSION_DB = os.environ.get('WA_SESSION', 'wa_session')
ENABLED = os.environ.get('WA_ENABLED', '1') not in ('0', 'false', 'False')

state = {
    'enabled': ENABLED,
    'sender': SENDER,
    'recipient': RECIPIENT,
    'connected': False,
    'pairing': False,
    'qr': None,
    'error': None,
    'last_send': None,
    'last_send_ok': None,
}

_lock = threading.RLock()
_connected_wait = threading.Event()
_qr_wait = threading.Event()

_pair = {'client': None, 'thread': None}


def _make_qr_png(qr_data: bytes) -> str:
    buf = io.BytesIO()
    segno.make_qr(qr_data).save(buf, kind='png', scale=6, border=2)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _build_client() -> NewClient:
    client = NewClient(SESSION_DB)
    state['connected'] = False
    state['qr'] = None

    def on_qr(_client, qr_bytes):
        state['qr'] = _make_qr_png(qr_bytes)
        state['pairing'] = True
        _qr_wait.set()

    def on_connected(_client, _event):
        state['connected'] = True
        state['pairing'] = False
        state['qr'] = None
        _connected_wait.set()
        if _pair['client'] is _client:
            _close_pair_soon()

    client.event.qr(on_qr)
    client.event(ConnectedEv)(on_connected)
    return client


def _stop_client(client: NewClient | None, thread: threading.Thread | None):
    if client is not None:
        try:
            client.stop()
        except Exception:
            log.exception('Error al cerrar conexión de WhatsApp')
    if thread is not None:
        thread.join(timeout=10)


def _close_pair_soon():
    threading.Timer(3.0, close_pair).start()


def close_pair():
    with _lock:
        client = _pair['client']
        thread = _pair['thread']
        if client is None:
            return
        _pair['client'] = None
        _pair['thread'] = None
    _stop_client(client, thread)


def start_pairing():
    with _lock:
        _connected_wait.clear()
        _qr_wait.clear()
        state['error'] = None
        if _pair['client'] is None:
            _pair['client'] = _build_client()
            _pair['thread'] = threading.Thread(target=_pair['client'].connect, daemon=True)
            _pair['thread'].start()
        return dict(state)


def pairing_status() -> dict:
    with _lock:
        return dict(state)


def send_new_letter(letter_id: int, letter_number: int, title: str, base_url: str) -> bool:
    if not ENABLED or not SENDER or not RECIPIENT:
        state['error'] = 'WhatsApp no configurado (faltan WA_SENDER/WA_RECIPIENT)'
        return False

    with _lock:
        if _pair['client'] is not None:
            state['error'] = 'Hay una vinculación en curso. Terminá de escanear el QR primero.'
            return False

        _connected_wait.clear()
        _qr_wait.clear()
        client = _build_client()
        thread = threading.Thread(target=client.connect, daemon=True)
        thread.start()
        try:
            if not _connected_wait.wait(25):
                if _qr_wait.is_set():
                    state['error'] = 'La cuenta aún no está vinculada. Visitá /wa para escanear el QR.'
                else:
                    state['error'] = 'No se pudo conectar a WhatsApp (timeout).'
                return False

            link = f"{base_url.rstrip('/')}/letter/{letter_id}"
            message = f"💌 Carta #{letter_number}: \"{title}\"\n{link}"
            client.send_message(RECIPIENT, message)
            state['last_send'] = time.time()
            state['last_send_ok'] = state['last_send']
            state['error'] = None
            return True
        except Exception as exc:
            log.exception('Error enviando notificación de WhatsApp')
            state['error'] = f'Error al enviar WhatsApp: {exc}'
            return False
        finally:
            _stop_client(client, thread)