"""
Assume Role na AWS usando o perfil SSO 'bastion'.
Mantém cache das credenciais para evitar chamadas redundantes.
"""
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Cache simples: {role_arn: {"credenciais": ..., "expira_em": timestamp}}
_cache_credenciais: dict = {}

# Margem de renovação antecipada (5 minutos antes de expirar)
_MARGEM_RENOVACAO = 300


def obter_sessao_com_role(role_arn: str, session_name: str = "OrquestradorSession") -> boto3.Session:
    """
    Retorna uma sessão boto3 com as credenciais do assume role.
    Usa cache para evitar múltiplas chamadas enquanto o token for válido.
    """
    agora = time.time()
    cache = _cache_credenciais.get(role_arn)

    if cache and cache["expira_em"] > agora + _MARGEM_RENOVACAO:
        logger.debug("Usando credenciais em cache para role '%s'.", role_arn)
        return _sessao_a_partir_de_credenciais(cache["credenciais"])

    logger.info("Obtendo credenciais via assume role para '%s'.", role_arn)
    credenciais = _fazer_assume_role(role_arn, session_name)

    # Calcular timestamp de expiração
    expira_em = credenciais["Expiration"].timestamp()
    _cache_credenciais[role_arn] = {"credenciais": credenciais, "expira_em": expira_em}

    return _sessao_a_partir_de_credenciais(credenciais)


def _fazer_assume_role(role_arn: str, session_name: str) -> dict:
    """Executa o assume role usando o perfil bastion configurado com SSO."""
    try:
        sessao_bastion = boto3.Session(profile_name="bastion")
        sts = sessao_bastion.client("sts")
        resposta = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
        return resposta["Credentials"]
    except ClientError as erro:
        logger.error("Falha no assume role para '%s': %s", role_arn, erro)
        raise


def _sessao_a_partir_de_credenciais(credenciais: dict) -> boto3.Session:
    """Cria uma sessão boto3 a partir de credenciais temporárias."""
    return boto3.Session(
        aws_access_key_id=credenciais["AccessKeyId"],
        aws_secret_access_key=credenciais["SecretAccessKey"],
        aws_session_token=credenciais["SessionToken"],
    )
