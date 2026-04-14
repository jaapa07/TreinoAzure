"""
NiFi REST API Client
Consome a API REST do Apache NiFi para coletar bulletins (erros/avisos),
status dos processadores e diagnósticos do sistema.
"""

import logging
import requests
import urllib3
from datetime import datetime
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class NiFiClient:
    """Cliente para a API REST do Apache NiFi."""

    SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}

    def __init__(self, base_url: str, username: str = "", password: str = "",
                 verify_ssl: bool = False, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        self._token: Optional[str] = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Autentica via username/password e armazena o token JWT."""
        if not self.username:
            return True  # Acesso sem autenticação

        url = f"{self.base_url}/nifi-api/access/token"
        try:
            resp = self.session.post(
                url,
                data={"username": self.username, "password": self.password},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            if resp.status_code == 201:
                self._token = resp.text.strip()
                self.session.headers.update(
                    {"Authorization": f"Bearer {self._token}"}
                )
                logger.info("Autenticação NiFi bem-sucedida.")
                return True
            logger.warning("Falha na autenticação NiFi: %s", resp.status_code)
            return False
        except requests.RequestException as exc:
            logger.error("Erro ao autenticar no NiFi: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        url = f"{self.base_url}/nifi-api{path}"
        try:
            resp = self.session.get(
                url, params=params, verify=self.verify_ssl, timeout=self.timeout
            )
            if resp.status_code == 401 and self.username:
                logger.info("Token expirado, reautenticando...")
                if self.login():
                    resp = self.session.get(
                        url, params=params, verify=self.verify_ssl,
                        timeout=self.timeout
                    )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.error("HTTP %s em %s: %s", exc.response.status_code, path, exc)
        except requests.RequestException as exc:
            logger.error("Erro de conexão em %s: %s", path, exc)
        return None

    # ------------------------------------------------------------------
    # Bulletin Board
    # ------------------------------------------------------------------

    def get_bulletins(self, after: int = 0) -> list[dict]:
        """Retorna bulletins do board (erros/avisos de processadores e sistema)."""
        data = self._get("/bulletin-board", params={"after": after})
        if not data:
            return []

        bulletins = []
        raw = data.get("bulletinBoard", {}).get("bulletins", [])
        for item in raw:
            b = item.get("bulletin", item)
            bulletins.append({
                "id": b.get("id", 0),
                "timestamp": b.get("timestamp", ""),
                "level": b.get("level", "INFO"),
                "category": b.get("category", ""),
                "message": b.get("message", ""),
                "sourceId": b.get("sourceId", ""),
                "sourceName": b.get("sourceName", ""),
                "groupId": b.get("groupId", ""),
                "groupName": b.get("groupName", ""),
                "nodeAddress": b.get("nodeAddress", ""),
                "parsed_time": self._parse_nifi_time(b.get("timestamp", "")),
            })

        # Ordena: erros primeiro, depois por timestamp desc
        bulletins.sort(
            key=lambda x: (
                self.SEVERITY_ORDER.get(x["level"].upper(), 99),
                -(x["id"] or 0),
            )
        )
        return bulletins

    # ------------------------------------------------------------------
    # Flow Status
    # ------------------------------------------------------------------

    def get_flow_status(self) -> Optional[dict]:
        """Retorna o status geral do fluxo NiFi."""
        data = self._get("/flow/status")
        if not data:
            return None
        s = data.get("controllerStatus", {})
        return {
            "activeThreadCount": s.get("activeThreadCount", 0),
            "terminatedThreadCount": s.get("terminatedThreadCount", 0),
            "queued": s.get("queued", "0 (0 bytes)"),
            "flowFilesQueued": s.get("flowFilesQueued", 0),
            "bytesQueued": s.get("bytesQueued", 0),
            "running": s.get("runningCount", 0),
            "stopped": s.get("stoppedCount", 0),
            "invalid": s.get("invalidCount", 0),
            "disabled": s.get("disabledCount", 0),
            "activeRemotePorts": s.get("activeRemotePortCount", 0),
            "inactiveRemotePorts": s.get("inactiveRemotePortCount", 0),
        }

    # ------------------------------------------------------------------
    # System Diagnostics
    # ------------------------------------------------------------------

    def get_system_diagnostics(self) -> Optional[dict]:
        """Retorna diagnósticos do sistema (CPU, memória, disco)."""
        data = self._get("/system-diagnostics")
        if not data:
            return None
        agg = data.get("systemDiagnostics", {}).get("aggregateSnapshot", {})
        return {
            "heapUsed": agg.get("usedHeap", "N/A"),
            "heapMax": agg.get("maxHeap", "N/A"),
            "heapUtilization": agg.get("heapUtilization", "N/A"),
            "nonHeapUsed": agg.get("usedNonHeap", "N/A"),
            "processorLoadAverage": agg.get("processorLoadAverage", "N/A"),
            "availableProcessors": agg.get("availableProcessors", "N/A"),
            "contentRepoStorageUsage": [
                {
                    "identifier": r.get("identifier", ""),
                    "usage": r.get("utilization", "N/A"),
                    "free": r.get("freeSpace", "N/A"),
                    "total": r.get("totalSpace", "N/A"),
                }
                for r in agg.get("contentRepositoryStorageUsage", [])
            ],
            "flowFileRepoStorageUsage": agg.get("flowFileRepositoryStorageUsage", {}),
        }

    # ------------------------------------------------------------------
    # Controller Bulletins
    # ------------------------------------------------------------------

    def get_controller_bulletins(self) -> list[dict]:
        """Retorna bulletins do controller (nível de cluster)."""
        data = self._get("/controller/bulletins")
        if not data:
            return []
        raw = data.get("bulletins", [])
        result = []
        for item in raw:
            b = item.get("bulletin", item)
            result.append({
                "id": b.get("id", 0),
                "timestamp": b.get("timestamp", ""),
                "level": b.get("level", "INFO"),
                "message": b.get("message", ""),
                "category": b.get("category", ""),
                "parsed_time": self._parse_nifi_time(b.get("timestamp", "")),
            })
        return result

    # ------------------------------------------------------------------
    # Cluster / Health
    # ------------------------------------------------------------------

    def get_cluster_summary(self) -> Optional[dict]:
        """Retorna resumo do cluster NiFi (single-node ou cluster)."""
        data = self._get("/flow/cluster/summary")
        if not data:
            return None
        cs = data.get("clusterSummary", {})
        return {
            "connectedToCluster": cs.get("connectedToCluster", False),
            "connectedNodes": cs.get("connectedNodes", "N/A"),
            "totalNodes": cs.get("totalNodeCount", "N/A"),
        }

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Verifica se o NiFi está acessível."""
        data = self._get("/flow/about")
        return data is not None

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_nifi_time(ts: str) -> str:
        """Converte timestamp NiFi para formato legível."""
        if not ts:
            return ""
        # NiFi retorna algo como "04/14/2026 10:30:45.123 UTC"
        for fmt in (
            "%m/%d/%Y %H:%M:%S.%f %Z",
            "%m/%d/%Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
        ):
            try:
                dt = datetime.strptime(ts, fmt)
                return dt.strftime("%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue
        return ts
