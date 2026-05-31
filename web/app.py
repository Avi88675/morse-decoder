"""
Web server — serves the UI and streams decoded text to the browser via WebSocket.

Architecture:
  Flask serves the HTML page at /
  Socket.IO pushes real-time events to connected browsers:
    'character' — one decoded character arrived
    'signal'    — frequency / strength / WPM update
  REST endpoints for logs, device list, status

MQTT (optional):
  If --mqtt-host is passed, each decoded character is also published to:
    morse/rx/char      — single character
    morse/rx/message   — flushed message (after silence)
  Home Assistant can subscribe to these via the MQTT integration.
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

app    = Flask(__name__)
app.config['SECRET_KEY'] = 'cw-decoder-secret'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# Module-level state — populated by setup_decoder()
_decoder      = None
_logger       = None
_source_info  = {}
_mqtt_client  = None


# ── REST endpoints ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', source=_source_info)

@app.route('/api/status')
def status():
    return jsonify({
        'connected': _decoder is not None,
        'source':    _source_info,
    })

@app.route('/api/logs')
def get_logs():
    n = int(request.args.get('n', 100))
    return jsonify(_logger.get_recent(n) if _logger else [])

@app.route('/api/devices')
def list_devices():
    from src.audio_source import SystemAudioSource
    return jsonify(SystemAudioSource.list_devices())


# ── WebSocket events ───────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    # Send recent log entries when a new browser connects
    if _logger:
        entries = _logger.get_recent(50)
        for e in entries:
            socketio.emit('log_entry', e, to=request.sid)
    # Send current sensitivity so UI slider syncs on reconnect
    if _decoder:
        factor = _decoder.tone_detector.threshold_factor
        sensitivity = int(round((1.0 - (factor - 0.2) / 0.5) * 100))
        socketio.emit('sensitivity', {'value': sensitivity}, to=request.sid)


@socketio.on('set_auto_sensitivity')
def on_set_auto(data):
    if _decoder:
        enabled = bool(data.get('enabled', True))
        _decoder.tone_detector.auto_sensitivity = enabled
        # If turning auto back on, let it re-learn from fresh history
        if enabled:
            _decoder.tone_detector._env_history.clear()
            _decoder.tone_detector._threshold = None
        socketio.emit('auto_sensitivity', {'enabled': enabled})


@socketio.on('set_sensitivity')
def on_set_sensitivity(data):
    """
    Browser sends sensitivity 0-100.
    0 = very sensitive (threshold_factor 0.2)
    100 = noise resistant (threshold_factor 0.7)
    Setting manually disables auto mode.
    """
    if _decoder:
        value = max(0, min(100, int(data.get('value', 50))))
        factor = 0.2 + (value / 100.0) * 0.5
        _decoder.tone_detector.threshold_factor = factor
        _decoder.tone_detector.auto_sensitivity = False
        _decoder.tone_detector._env_history.clear()
        _decoder.tone_detector._threshold = None
        socketio.emit('sensitivity', {'value': value, 'auto': False})


@app.route('/api/sensitivity', methods=['GET', 'POST'])
def sensitivity():
    if not _decoder:
        return jsonify({'error': 'decoder not running'}), 503
    if request.method == 'POST':
        value = max(0, min(100, int(request.json.get('value', 50))))
        factor = 0.2 + (value / 100.0) * 0.5
        _decoder.tone_detector.threshold_factor = factor
        _decoder.tone_detector._env_history.clear()
        return jsonify({'value': value, 'threshold_factor': round(factor, 3)})
    factor = _decoder.tone_detector.threshold_factor
    value = int(round((factor - 0.2) / 0.5 * 100))
    return jsonify({'value': value, 'threshold_factor': round(factor, 3)})


# ── Setup (called by main.py) ──────────────────────────────────

def setup_decoder(source, decoder, logger, mqtt_host=None, mqtt_port=1883):
    """Wire up decoder callbacks and start the audio source."""
    global _decoder, _logger, _source_info, _mqtt_client

    _decoder     = decoder
    _logger      = logger
    _source_info = source.get_info()

    # ── Optional MQTT setup ────────────────────────────────────
    if mqtt_host:
        try:
            import paho.mqtt.client as mqtt
            _mqtt_client = mqtt.Client()
            _mqtt_client.connect(mqtt_host, mqtt_port, keepalive=60)
            _mqtt_client.loop_start()
            print(f"  📡 MQTT connected to {mqtt_host}:{mqtt_port}")
        except Exception as e:
            print(f"  ⚠️  MQTT connection failed: {e}")
            _mqtt_client = None

    # ── Character callback ─────────────────────────────────────
    def on_character(char: str):
        # Push to all connected browsers
        socketio.emit('character', {'char': char})

        # Log it
        if _logger:
            _logger.on_character(char)

        # MQTT publish
        if _mqtt_client:
            try:
                _mqtt_client.publish('morse/rx/char', char)
            except Exception:
                pass

    # ── Signal state callback ──────────────────────────────────
    _sig_counter = [0]
    def on_signal(freq: float, strength: float, is_mark: bool, wpm: int):
        # Include threshold_factor every 10 signals so UI slider tracks auto mode
        _sig_counter[0] += 1
        payload = {
            'frequency': round(freq, 1),
            'strength':  round(strength, 3),
            'active':    bool(is_mark),
            'wpm':       int(wpm),
        }
        if _sig_counter[0] % 10 == 0:
            factor = decoder.tone_detector.threshold_factor
            auto   = decoder.tone_detector.auto_sensitivity
            payload['sensitivity'] = int(round((factor - 0.2) / 0.5 * 100))
            payload['auto'] = auto
        socketio.emit('signal', payload)

    decoder.on_character(on_character)
    decoder.on_signal_state(on_signal)
    source.start(decoder.feed)


def run_server(host: str = '0.0.0.0', port: int = 5000):
    """Start the web server. Blocks until Ctrl+C."""
    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        use_reloader=False,   # important: reloader conflicts with audio threads
    )
