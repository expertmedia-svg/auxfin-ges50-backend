"""Client HTTP vers l'API de controle locale du service Node whatsapp-gateway
(demarrage/arret/QR/liste des groupes). N'est jamais appele pour les
evenements temps reel (messages/heartbeats) : ceux-ci arrivent en sens
inverse via les webhooks /api/whatsapp/webhook/*."""

from __future__ import annotations

import httpx

from app.core.config import get_settings

settings = get_settings()

_TIMEOUT_SECONDS = 5.0


class GatewayUnavailableError(Exception):
    """Le service whatsapp-gateway n'est pas joignable (pas demarre, port ferme, etc.)."""


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.whatsapp_gateway_url, timeout=_TIMEOUT_SECONDS)


def get_control_status() -> dict:
    try:
        with _client() as client:
            response = client.get("/control/status")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise GatewayUnavailableError(str(exc)) from exc


def start_session() -> dict:
    try:
        with _client() as client:
            response = client.post("/control/start")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise GatewayUnavailableError(str(exc)) from exc


def stop_session() -> dict:
    try:
        with _client() as client:
            response = client.post("/control/stop")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise GatewayUnavailableError(str(exc)) from exc


def refresh_groups() -> list[dict]:
    try:
        with _client() as client:
            response = client.post("/control/refresh-groups")
            response.raise_for_status()
            return response.json()["groups"]
    except httpx.HTTPError as exc:
        raise GatewayUnavailableError(str(exc)) from exc
