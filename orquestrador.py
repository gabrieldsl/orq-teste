"""
Orquestrador principal.
Processa registros do DataFrame individualmente:
  1. Consulta CloudTrail
  2. Se não houver logs, encerra o registro com mensagem informativa
  3. Se houver logs, envia ao agente StackSpot
  4. Persiste resultado imediatamente no arquivo de saída
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from aws.extrator_logs_aws import extrair_logs
from stackspot.process_stackspot import enviar_para_agente

logger = logging.getLogger(__name__)

ARQUIVO_SAIDA = Path("resultado.json")

# Lock para escrita segura no arquivo de saída entre threads
import threading
_lock_escrita = threading.Lock()


def _processar_registro(registro: dict, max_tentativas: int) -> dict:
    """
    Processa um único registro com retry exponencial.
    Retorna o registro enriquecido com logs e resposta do agente.
    """
    account_id = registro.get("account_id", "?")

    for tentativa in range(1, max_tentativas + 1):
        try:
            # ── Etapa 1: CloudTrail ──────────────────────────────────────────
            logger.info("[%s] Tentativa %d/%d — consultando CloudTrail.", account_id, tentativa, max_tentativas)
            logs_aws = extrair_logs(registro)
            registro["logs_cloudtrail"] = logs_aws

            # ── Short-circuit: sem logs, não envia ao StackSpot ──────────────
            if not logs_aws:
                logger.info("[%s] Nenhuma log identificada. Pulando envio ao StackSpot.", account_id)
                registro["resposta_agente"] = f"Nenhuma log identificada para account_id {account_id}."
                return registro

            # ── Etapa 2: StackSpot ───────────────────────────────────────────
            logger.info("[%s] Tentativa %d/%d — enviando ao agente StackSpot.", account_id, tentativa, max_tentativas)
            registro["resposta_agente"] = enviar_para_agente(registro)
            return registro

        except Exception as erro:
            logger.warning("[%s] Erro na tentativa %d/%d: %s", account_id, tentativa, max_tentativas, erro)
            if tentativa < max_tentativas:
                espera = 2 ** tentativa  # backoff exponencial: 2s, 4s, 8s
                logger.info("[%s] Aguardando %ds antes de nova tentativa.", account_id, espera)
                time.sleep(espera)
            else:
                logger.error("[%s] Todas as tentativas falharam.", account_id)
                registro["logs_cloudtrail"] = []
                registro["resposta_agente"] = None
                registro["erro"] = str(erro)
                return registro


def _persistir_registro(registro: dict) -> None:
    """Anexa um registro ao arquivo JSON de saída de forma thread-safe."""
    with _lock_escrita:
        try:
            dados = json.loads(ARQUIVO_SAIDA.read_text(encoding="utf-8"))
            dados.append(registro)
            ARQUIVO_SAIDA.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as erro:
            logger.error("Falha ao persistir registro no arquivo: %s", erro)


def executar(df: pd.DataFrame) -> None:
    """
    Ponto de entrada do orquestrador.
    Recebe o DataFrame e processa cada registro de forma concorrente.
    """
    workers = int(os.getenv("WORKERS", 3))
    max_tentativas = int(os.getenv("MAX_TENTATIVAS", 3))
    total = len(df)

    logger.info("Iniciando orquestração | registros=%d | workers=%d | max_tentativas=%d.", total, workers, max_tentativas)

    # Garante arquivo de saída limpo a cada execução
    ARQUIVO_SAIDA.write_text("[]", encoding="utf-8")

    registros = df.to_dict(orient="records")

    barra_logs = tqdm(total=total, desc="CloudTrail ", position=0, unit="reg", leave=True)
    barra_stackspot = tqdm(total=total, desc="StackSpot  ", position=1, unit="reg", leave=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {
            executor.submit(_processar_registro, registro, max_tentativas): registro.get("account_id", "?")
            for registro in registros
        }

        for futuro in as_completed(futuros):
            account_id = futuros[futuro]
            try:
                resultado = futuro.result()
                _persistir_registro(resultado)
                logger.info("[%s] Registro processado e persistido.", account_id)
            except Exception as erro:
                logger.error("[%s] Erro inesperado: %s", account_id, erro)
            finally:
                barra_logs.update(1)
                barra_stackspot.update(1)

    barra_logs.close()
    barra_stackspot.close()
    logger.info("Orquestração concluída. Resultados em '%s'.", ARQUIVO_SAIDA)
