"""
Configuração centralizada de logs.
- Console : apenas INFO
- Arquivo : WARNING e ERROR para debug
"""
import logging
import logging.handlers
from pathlib import Path


def iniciar_logger(nome_arquivo: str = "execucao.log") -> None:
    """Inicializa o logger raiz com handlers para console e arquivo."""
    logger_raiz = logging.getLogger()
    logger_raiz.setLevel(logging.DEBUG)

    formato = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console — somente INFO
    handler_console = logging.StreamHandler()
    handler_console.setLevel(logging.INFO)
    handler_console.setFormatter(formato)

    # Arquivo — WARNING e ERROR
    handler_arquivo = logging.handlers.RotatingFileHandler(
        Path(nome_arquivo), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    handler_arquivo.setLevel(logging.WARNING)
    handler_arquivo.setFormatter(formato)

    logger_raiz.addHandler(handler_console)
    logger_raiz.addHandler(handler_arquivo)

    # Silenciar bibliotecas ruidosas
    for lib in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(lib).setLevel(logging.ERROR)

    logging.getLogger(__name__).info(
        "Logger inicializado. Logs WARNING+ salvos em '%s'.", nome_arquivo
    )
