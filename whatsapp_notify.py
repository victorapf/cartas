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

_pair = {'client': None, 'thread': None, 'holder': None}


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
        state['error'] = None
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


def _runner(holder: dict):
    client = holder['client']
    try:
        holder['err'] = client.connect()
    except BaseException as exc:
        holder['exc'] = exc
    finally:
        holder['done'] = True


def _start_thread(client: NewClient):
    holder = {'client': client, 'done': False, 'err': None, 'exc': None}
    thread = threading.Thread(target=_runner, args=(holder,), daemon=True)
    thread.start()
    _pair['client'] = client
    _pair['thread'] = thread
    _pair['holder'] = holder
    return thread, holder


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


def close_pair(clear_error: bool = True):
    with _lock:
        client = _pair['client']
        thread = _pair['thread']
        if client is None:
            return
        _pair['client'] = None
        _pair['thread'] = None
        _pair['holder'] = None
    _stop_client(client, thread)
    if clear_error:
        state['error'] = None


def _check_dead_thread():
    holder = _pair.get('holder')
    thread = _pair.get('thread')
    if holder is None or thread is None:
        return
    if holder.get('done'):
        pair = _pair['client']
        _pair['client'] = None
        _pair['thread'] = None
        _pair['holder'] = None
        if holder.get('exc'):
            err = str(holder['exc'])
        elif holder.get('err'):
            err = str(holder['err'])
        else:
            err = 'La conexión terminó sin QR ni conexión'
        state['error'] = err
        state['pairing'] = False
        log.error('Thread WhatsApp murió: %s', err)
        if pair is not None:
            try:
                pair.stop()
            except Exception:
                pass


def reset_session():
    with _lock:
        close_pair(clear_error=False)
    removed = False
    for path in (SESSION_DB, f'{SESSION_DB}.db', f'{SESSION_DB}.sqlite'):
        if os.path.exists(path):
            try:
                os.remove(path)
                removed = True
            except OSError as exc:
                state['error'] = f'No se pudo borrar la sesión: {exc}'
                return False
    state['error'] = None
    state['connected'] = False
    state['pairing'] = False
    state['qr'] = None
    return removed


def start_pairing():
    with _lock:
        _check_dead_thread()
        _connected_wait.clear()
        _qr_wait.clear()
        state['error'] = None
        if _pair['client'] is None:
            client = _build_client()
            _start_thread(client)
        return dict(state)


def pairing_status() -> dict:
    with _lock:
        _check_dead_thread()
        holder = _pair.get('holder')
        if holder and holder.get('done'):
            state['error'] = state['error'] or 'La conexión terminó sin generar QR'
        return dict(state)


def send_new_letter(letter_id: int, letter_number: int, title: str, base_url: str) -> bool:
    if not ENABLED or not SENDER or not RECIPIENT:
        state['error'] = 'WhatsApp no configurado (faltan WA_SENDER/WA_RECIPIENT)'
        return False

    with _lock:
        if _pair['client'] is not None:
            _check_dead_thread()
            if _pair['client'] is not None:
                state['error'] = 'Hay una vinculación en curso. Terminá de escanear el QR primero.'
                return False

        _connected_wait.clear()
        _qr_wait.clear()
        client = _build_client()
        holder = {'client': client, 'done': False, 'err': None, 'exc': None}
        thread = threading.Thread(target=_runner, args=(holder,), daemon=True)
        thread.start()
        try:
            if not _connected_wait.wait(25):
                if _qr_wait.is_set():
                    state['error'] = 'La cuenta aún no está vinculada. Visitá /wa para escanear el QR.'
                else:
                    state['error'] = _thread_error(holder) or 'No se pudo conectar a WhatsApp (timeout).'
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


def _thread_error(holder: dict) -> str | None:
    if holder.get('done'):
        if holder.get('exc'):
            return f'Error al conectar: {holder["exc"]}'
        if holder.get('err'):
            return f'Error al conectar: {holder["err"]}'
        return 'La conexión terminó sin generar QR'
    return None