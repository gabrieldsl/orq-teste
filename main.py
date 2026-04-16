import logging
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from orquestrador import executar
from utils.logging_config import iniciar_logger

load_dotenv()

# Inicializa o sistema de logs
iniciar_logger("execucao.log")

logger = logging.getLogger(__name__)


def _formatar_duracao(segundos: float) -> str:
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    segs = int(segundos % 60)
    return f"{horas:02d}h {minutos:02d}m {segs:02d}s"


def main() -> None:
    if len(sys.argv) < 2:
        logger.error("Uso: python main.py <caminho_do_arquivo.csv>")
        sys.exit(1)

    caminho_csv = Path(sys.argv[1])
    if not caminho_csv.exists():
        logger.error("Arquivo não encontrado: %s", caminho_csv)
        sys.exit(1)

    logger.info("Carregando arquivo: %s", caminho_csv)
    df = pd.read_csv(caminho_csv)
    total_registros = len(df)
    logger.info("Total de registros carregados: %d", total_registros)

    inicio = time.time()
    executar(df)
    duracao_total = time.time() - inicio

    media_por_registro = duracao_total / total_registros if total_registros > 0 else 0.0

    logger.info("─" * 50)
    logger.info("Execução finalizada.")
    logger.info("Tempo total    : %s", _formatar_duracao(duracao_total))
    logger.info("Média/registro : %.2f segundos", media_por_registro)
    logger.info("─" * 50)


if __name__ == "__main__":
    main()
