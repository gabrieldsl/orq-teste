"""
Extrator de logs do CloudTrail.
Recebe um registro JSON com account_id, data_inicio e data_fim,
executa a query SQL via start_query e coleta o resultado via get_query_results.
"""
import logging
import os
import time

from aws.aws_auth import GerenciadorAuth

logger = logging.getLogger(__name__)

REGIAO_PADRAO = "sa-east-1"
padrao_role = "arn:aws:iam::{account_id}:role/sua-role"
query_padrao = "SELECT eventTime, eventName, userIdentity.arn, sourceIPAddress, requestParameters FROM cloudtrail_logs WHERE recipientAccountId = '{account_id}' AND eventTime >= '{data_inicio}' AND eventTime <= '{data_fim}' ORDER BY eventTime DESC LIMIT 100"

# Instância singleton do gerenciador de autenticação (inicializada na primeira chamada)
_gerenciador_auth: GerenciadorAuth | None = None

##### CHUMBAR ESSAS INFORMAÇÕES AQUI
def _obter_gerenciador() -> GerenciadorAuth:
    """Retorna o singleton do GerenciadorAuth, criando-o se necessário."""
    global _gerenciador_auth
    if _gerenciador_auth is None:
        _gerenciador_auth = GerenciadorAuth(
            sso_start_url=os.environ["AWS_SSO_START_URL"],
            sso_region=os.environ["AWS_SSO_REGION"],
            sso_account_id=os.environ["AWS_SSO_ACCOUNT_ID"],
            sso_role_name=os.environ["AWS_SSO_ROLE_NAME"],
            regiao_padrao=os.getenv("AWS_DEFAULT_REGION", REGIAO_PADRAO),
            nome_sessao="OrquestradorSession",
            duracao_sessao= 3600,
        )
    return _gerenciador_auth


def extrair_logs(registro: dict) -> list[dict]:
    """
    Consulta o CloudTrail para a conta e período informados no registro.
    Retorna lista de eventos ou lista vazia se nenhum evento for encontrado.
    """
    account_id = registro["account_id"]
    data_inicio = registro["data_inicio"]
    data_fim = registro["data_fim"]

    role_arn = padrao_role.format(account_id=account_id)
    
    query_sql = query_padrao.format(
        account_id=account_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    logger.info("[%s] Iniciando extração de logs (de: %s | até: %s).", account_id, data_inicio, data_fim)

    gerenciador = _obter_gerenciador()
    cliente_ct = gerenciador.obter_cliente(
        "cloudtrail",
        role_arn=role_arn,
        regiao=os.getenv("AWS_DEFAULT_REGION", REGIAO_PADRAO),
    )

    # Inicia a query — sem DeliveryS3Uri (usa armazenamento gerenciado)
    resp_query = cliente_ct.start_query(QueryStatement=query_sql)
    query_id = resp_query["QueryId"]
    logger.debug("[%s] Query iniciada | ID: %s.", account_id, query_id)

    eventos = _aguardar_e_coletar(cliente_ct, query_id, account_id)
    logger.info("[%s] Extração concluída — %d evento(s) encontrado(s).", account_id, len(eventos))
    return eventos


def _aguardar_e_coletar(cliente_ct, query_id: str, account_id: str) -> list[dict]:
    """Aguarda conclusão da query e retorna todos os resultados paginados."""
    STATUS_FINAIS = {"FINISHED", "FAILED", "CANCELLED", "TIMED_OUT"}
    intervalo = 2  # segundos entre verificações

    while True:
        resp_status = cliente_ct.get_query_results(QueryId=query_id)
        status = resp_status.get("QueryStatus")

        if status in STATUS_FINAIS:
            if status != "FINISHED":
                raise RuntimeError(
                    f"[{account_id}] Query {query_id} encerrou com status '{status}'."
                )
            # Primeira página já está na resposta do status
            return _coletar_paginas(cliente_ct, query_id, resp_status)

        logger.debug("[%s] Aguardando query %s (status: %s)...", account_id, query_id, status)
        time.sleep(intervalo)


def _coletar_paginas(cliente_ct, query_id: str, primeira_pagina: dict) -> list[dict]:
    """Coleta todas as páginas de resultado e converte para lista de dicts."""
    eventos: list[dict] = []

    def _processar_pagina(pagina: dict) -> None:
        for linha in pagina.get("QueryResultRows", []):
            # Cada linha é uma lista de dicts {"key": ..., "value": ...}
            eventos.append({col["key"]: col["value"] for col in linha})

    _processar_pagina(primeira_pagina)
    next_token = primeira_pagina.get("NextToken")

    while next_token:
        pagina = cliente_ct.get_query_results(QueryId=query_id, NextToken=next_token)
        _processar_pagina(pagina)
        next_token = pagina.get("NextToken")

    return eventos
