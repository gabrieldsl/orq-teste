"""
Cliente para o Agente StackSpot AI.
Gerencia autenticação com cache de token e envia registros para o agente.
"""
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Cache do token: {"access_token": str, "expira_em": float (timestamp)}
_cache_token: dict = {}

# Margem de renovação antecipada (60 segundos antes de expirar)
_MARGEM_RENOVACAO = 60


def _obter_token() -> str:
    """Retorna o access token, renovando apenas quando necessário."""
    agora = time.time()

    if _cache_token and _cache_token["expira_em"] > agora + _MARGEM_RENOVACAO:
        logger.debug("Usando token StackSpot em cache.")
        return _cache_token["access_token"]

    logger.info("Obtendo novo token de autenticação StackSpot.")
    url = f"TROCAR URL"

    resposta = requests.post(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": os.environ["STACKSPOT_CLIENT_ID"],
            "client_secret": os.environ["STACKSPOT_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    resposta.raise_for_status()

    dados = resposta.json()
    _cache_token["access_token"] = dados["access_token"]
    _cache_token["expira_em"] = agora + dados.get("expires_in", 3600)

    logger.info("Token StackSpot obtido com sucesso.")
    return _cache_token["access_token"]


def enviar_para_agente(registro: dict) -> str:
    """
    Envia o registro JSON para o agente StackSpot configurado.
    Retorna apenas o conteúdo do campo 'message' da resposta.
    """
    agent_id = os.environ["STACKSPOT_AGENT_ID"]
    
    #### ATUALIZAR URL AQUI
    url = f"TROCAR_AQUI{agent_id}/chat"
    account_id = registro.get("account_id", "?")

    token = _obter_token()

    payload = {
        "streaming": False,
        "user_prompt": str(registro),
        "stackspot_knowledge": True,
        "return_ks_in_response": False,
    }

    logger.info("[%s] Enviando registro ao agente StackSpot.", account_id)
    logger.debug("[%s] Payload: %s", account_id, payload)

    resposta = requests.post(
        url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        timeout=120,
    )
    resposta.raise_for_status()

    dados = resposta.json()
    mensagem = dados.get("message", "")
    logger.info("[%s] Resposta recebida do agente StackSpot.", account_id)
    logger.debug("[%s] Resposta completa: %s", account_id, dados)

    return mensagem
