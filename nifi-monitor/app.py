"""
NiFi Error Monitor - Backend Flask
Dashboard web para monitoramento de erros do Apache NiFi.

Endpoints:
  GET /               -> Dashboard HTML
  GET /api/status     -> JSON com status geral + bulletins
  GET /api/bulletins  -> JSON só dos bulletins
  GET /stream         -> Server-Sent Events (atualizações em tempo real)
"""

import json
import logging
import os
import time
import threading
from collections import deque
from datetime import datetime
from typing import Generator

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from nifi_client import NiFiClient

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

NIFI_BASE_URL = os.getenv("NIFI_BASE_URL", "https://nifi-tierc.lincros.com/nifi")
NIFI_USERNAME = os.getenv("NIFI_USERNAME", "")
NIFI_PASSWORD = os.getenv("NIFI_PASSWORD", "")
NIFI_VERIFY_SSL = os.getenv("NIFI_VERIFY_SSL", "false").lower() == "true"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))   # segundos
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "500"))       # máx bulletins no cache
ALERT_LEVELS = {"ERROR", "CRITICAL"}

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Estado compartilhado (thread-safe via Lock)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state = {
    "last_update": None,
    "nifi_online": False,
    "bulletins": deque(maxlen=MAX_HISTORY),   # todos os bulletins coletados
    "flow_status": {},
    "system": {},
    "cluster": {},
    "error_count": 0,
    "warning_count": 0,
    "last_bulletin_id": 0,
}

from queue import Queue

# SSE: fila de eventos para clientes conectados
_sse_listeners: list[Queue] = []

# ---------------------------------------------------------------------------
# Polling em background
# ---------------------------------------------------------------------------

def _collect_data():
    """Coleta dados do NiFi e atualiza o estado global."""
    client = NiFiClient(
        base_url=NIFI_BASE_URL,
        username=NIFI_USERNAME,
        password=NIFI_PASSWORD,
        verify_ssl=NIFI_VERIFY_SSL,
    )
    if NIFI_USERNAME:
        client.login()

    global _state

    while True:
        try:
            online = client.ping()
            flow = client.get_flow_status() or {}
            system = client.get_system_diagnostics() or {}
            cluster = client.get_cluster_summary() or {}

            with _lock:
                after_id = _state["last_bulletin_id"]

            bulletins = client.get_bulletins(after=after_id)
            controller_bulletins = client.get_controller_bulletins()

            # Merge controller bulletins (não têm IDs sequenciais, evita duplicatas)
            existing_msgs = set()
            with _lock:
                for b in _state["bulletins"]:
                    existing_msgs.add((b["message"], b["timestamp"]))

            new_bulletins = []
            for b in bulletins + controller_bulletins:
                key = (b["message"], b["timestamp"])
                if key not in existing_msgs:
                    new_bulletins.append(b)
                    existing_msgs.add(key)

            with _lock:
                for b in new_bulletins:
                    _state["bulletins"].appendleft(b)
                    if b["id"] and b["id"] > _state["last_bulletin_id"]:
                        _state["last_bulletin_id"] = b["id"]

                _state["nifi_online"] = online
                _state["flow_status"] = flow
                _state["system"] = system
                _state["cluster"] = cluster
                _state["last_update"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                all_b = list(_state["bulletins"])
                _state["error_count"] = sum(
                    1 for b in all_b if b["level"].upper() in ALERT_LEVELS
                )
                _state["warning_count"] = sum(
                    1 for b in all_b if b["level"].upper() == "WARNING"
                )

            # Notifica clientes SSE
            if new_bulletins:
                event_data = json.dumps({
                    "type": "new_bulletins",
                    "count": len(new_bulletins),
                    "bulletins": new_bulletins[:10],  # envia só os 10 mais recentes
                    "error_count": _state["error_count"],
                    "warning_count": _state["warning_count"],
                    "last_update": _state["last_update"],
                })
                _broadcast_sse(event_data)
            else:
                # Heartbeat mesmo sem novos bulletins
                event_data = json.dumps({
                    "type": "heartbeat",
                    "nifi_online": _state["nifi_online"],
                    "last_update": _state["last_update"],
                    "error_count": _state["error_count"],
                    "warning_count": _state["warning_count"],
                })
                _broadcast_sse(event_data)

            logger.info(
                "Poll concluído: online=%s, novos=%d, erros=%d",
                online, len(new_bulletins), _state["error_count"]
            )

        except Exception as exc:
            logger.exception("Erro inesperado no polling: %s", exc)

        time.sleep(POLL_INTERVAL)


def _broadcast_sse(data: str):
    """Envia evento SSE para todos os clientes conectados."""
    dead = []
    for q in _sse_listeners:
        try:
            q.put_nowait(data)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _sse_listeners.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Rotas Flask
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    with _lock:
        state_snapshot = {
            "nifi_url": NIFI_BASE_URL,
            "nifi_online": _state["nifi_online"],
            "last_update": _state["last_update"],
            "error_count": _state["error_count"],
            "warning_count": _state["warning_count"],
            "poll_interval": POLL_INTERVAL,
            "flow_status": _state["flow_status"],
            "system": _state["system"],
            "cluster": _state["cluster"],
            "bulletins": list(_state["bulletins"])[:100],
        }
    return render_template("index.html", **state_snapshot)


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({
            "nifi_url": NIFI_BASE_URL,
            "nifi_online": _state["nifi_online"],
            "last_update": _state["last_update"],
            "error_count": _state["error_count"],
            "warning_count": _state["warning_count"],
            "flow_status": _state["flow_status"],
            "system": _state["system"],
            "cluster": _state["cluster"],
        })


@app.route("/api/bulletins")
def api_bulletins():
    level_filter = request.args.get("level", "").upper()
    limit = min(int(request.args.get("limit", 200)), MAX_HISTORY)

    with _lock:
        bulletins = list(_state["bulletins"])

    if level_filter:
        bulletins = [b for b in bulletins if b["level"].upper() == level_filter]

    return jsonify({"total": len(bulletins), "bulletins": bulletins[:limit]})


@app.route("/stream")
def stream():
    """Server-Sent Events: envia atualizações em tempo real para o browser."""
    q: Queue = Queue(maxsize=50)
    _sse_listeners.append(q)

    @stream_with_context
    def event_stream() -> Generator:
        try:
            # Envia estado inicial imediatamente
            with _lock:
                initial = json.dumps({
                    "type": "init",
                    "nifi_online": _state["nifi_online"],
                    "last_update": _state["last_update"],
                    "error_count": _state["error_count"],
                    "warning_count": _state["warning_count"],
                    "bulletins": list(_state["bulletins"])[:50],
                })
            yield f"data: {initial}\n\n"

            while True:
                try:
                    data = q.get(timeout=30)
                    yield f"data: {data}\n\n"
                except Exception:
                    # Timeout -> envia keep-alive
                    yield ": keep-alive\n\n"
        finally:
            try:
                _sse_listeners.remove(q)
            except ValueError:
                pass

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Força reconexão e novo poll (útil para testes)."""
    return jsonify({"message": "Próximo ciclo de polling em andamento.", "interval": POLL_INTERVAL})


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def main():
    # Inicia thread de polling em background
    poller = threading.Thread(target=_collect_data, daemon=True, name="nifi-poller")
    poller.start()
    logger.info("Iniciando NiFi Monitor em http://0.0.0.0:5000")
    logger.info("NiFi URL: %s | Polling a cada %ds", NIFI_BASE_URL, POLL_INTERVAL)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
