"""
Módulo de autenticação AWS via SSO + STS AssumeRole.

Fluxo:
1. Lê token SSO do cache local (~/.aws/sso/cache/) gerado pelo 'aws sso login'
2. Troca o token SSO por credenciais IAM via sso:GetRoleCredentials (conta bastion)
3. Usa essas credenciais para fazer sts:AssumeRole nas contas-alvo (cross-account)
4. Cache thread-safe com renovação automática antes da expiração
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Margem de renovação antecipada (segundos antes de expirar)
_BUFFER_RENOVACAO = 120


# ── Data class de credenciais ──────────────────────────────────────────────────

@dataclass
class Credenciais:
    """Credenciais IAM temporárias com metadados de validade."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    assumed_role_arn: Optional[str] = None

    @property
    def validas(self) -> bool:
        agora = datetime.now(tz=timezone.utc)
        exp = self.expiration
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return (exp - agora).total_seconds() > _BUFFER_RENOVACAO

    @property
    def expira_em_segundos(self) -> float:
        agora = datetime.now(tz=timezone.utc)
        exp = self.expiration
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return max(0.0, (exp - agora).total_seconds())

    def para_boto3(self) -> Dict[str, str]:
        return {
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
            "aws_session_token": self.session_token,
        }

    def __repr__(self) -> str:
        chave = f"{self.access_key_id[:4]}...{self.access_key_id[-4:]}"
        return (
            f"Credenciais(key={chave}, role={self.assumed_role_arn or 'base'}, "
            f"expira_em={self.expira_em_segundos:.0f}s)"
        )


# ── Leitor do cache SSO ────────────────────────────────────────────────────────

class _CacheSSO:
    """Lê tokens de acesso SSO do cache local gerado pelo AWS CLI."""

    DIRETORIO = Path.home() / ".aws" / "sso" / "cache"

    @classmethod
    def buscar_token(cls, sso_start_url: str) -> Optional[Dict[str, Any]]:
        """Localiza token SSO válido no cache local para a start URL informada."""
        if not cls.DIRETORIO.exists():
            logger.warning(
                "Diretório de cache SSO não encontrado: %s. Execute 'aws sso login'.",
                cls.DIRETORIO,
            )
            return None

        # Tenta correspondência por SHA1 da URL (padrão AWS CLI v2)
        url_hash = hashlib.sha1(sso_start_url.encode("utf-8")).hexdigest()
        candidato = cls.DIRETORIO / f"{url_hash}.json"

        if candidato.exists():
            return cls._ler_e_validar(candidato)

        # Fallback: varre todos os arquivos no cache
        for arquivo in cls.DIRETORIO.glob("*.json"):
            dados = cls._ler_json(arquivo)
            if dados and dados.get("startUrl") == sso_start_url:
                return cls._validar_token(dados, arquivo)

        logger.error(
            "Nenhum token SSO válido encontrado para %s. Execute 'aws sso login --profile bastion'.",
            sso_start_url,
        )
        return None

    @classmethod
    def _ler_e_validar(cls, caminho: Path) -> Optional[Dict[str, Any]]:
        dados = cls._ler_json(caminho)
        return cls._validar_token(dados, caminho) if dados else None

    @staticmethod
    def _ler_json(caminho: Path) -> Optional[Dict[str, Any]]:
        try:
            with caminho.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            logger.debug("Falha ao ler arquivo de cache SSO %s: %s", caminho, exc)
            return None

    @staticmethod
    def _validar_token(dados: Dict[str, Any], caminho: Path) -> Optional[Dict[str, Any]]:
        expires_str = dados.get("expiresAt", "")
        if not expires_str:
            return None
        try:
            expira_em = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            agora = datetime.now(tz=timezone.utc)
            if expira_em.tzinfo is None:
                expira_em = expira_em.replace(tzinfo=timezone.utc)
            if expira_em <= agora:
                logger.warning("Token SSO em %s está expirado. Execute 'aws sso login'.", caminho)
                return None
            logger.debug("Token SSO válido encontrado | arquivo=%s | expira_em=%.0fs", caminho.name, (expira_em - agora).total_seconds())
            return dados
        except ValueError as exc:
            logger.warning("Falha ao interpretar expiração do token SSO em %s: %s", caminho, exc)
            return None


# ── Gerenciador de autenticação ────────────────────────────────────────────────

class GerenciadorAuth:
    """
    Gerenciador de autenticação AWS (SSO + AssumeRole cross-account).
    Thread-safe com cache de credenciais por ARN.
    """

    def __init__(
        self,
        sso_start_url: str,
        sso_region: str,
        sso_account_id: str,
        sso_role_name: str,
        regiao_padrao: str = "sa-east-1",
        nome_sessao: str = "OrquestradorSession",
        duracao_sessao: int = 3600,
    ) -> None:
        self._sso_start_url = sso_start_url
        self._sso_region = sso_region
        self._sso_account_id = sso_account_id
        self._sso_role_name = sso_role_name
        self._regiao_padrao = regiao_padrao
        self._nome_sessao = nome_sessao
        self._duracao_sessao = duracao_sessao

        self._lock = threading.Lock()
        self._cache: Dict[str, Credenciais] = {}

    # ── API pública ────────────────────────────────────────────────────────────

    def assume_role(self, role_arn: str) -> Credenciais:
        """
        Realiza AssumeRole cross-account usando credenciais base SSO.
        Retorna credenciais com cache automático.
        """
        return self._obter_ou_renovar(role_arn, lambda: self._executar_assume_role(role_arn))

    def obter_cliente(self, servico: str, role_arn: str, regiao: Optional[str] = None) -> Any:
        """Retorna um boto3 client autenticado para a role informada."""
        creds = self.assume_role(role_arn)
        sessao = boto3.Session(
            region_name=regiao or self._regiao_padrao,
            **creds.para_boto3(),
        )
        return sessao.client(servico)

    # ── Credenciais base (SSO) ─────────────────────────────────────────────────

    def _obter_credenciais_base(self) -> Credenciais:
        """Obtém credenciais IAM da conta bastion via SSO GetRoleCredentials."""
        return self._obter_ou_renovar("__base__", self._buscar_credenciais_sso)

    def _buscar_credenciais_sso(self) -> Credenciais:
        logger.info(
            "Obtendo credenciais SSO | conta=%s | role=%s",
            self._sso_account_id, self._sso_role_name,
        )
        dados_token = _CacheSSO.buscar_token(self._sso_start_url)
        if not dados_token:
            raise RuntimeError(
                f"Token SSO não encontrado para {self._sso_start_url}. "
                "Execute 'aws sso login --profile bastion'."
            )

        cliente_sso = boto3.client("sso", region_name=self._sso_region)
        try:
            resp = cliente_sso.get_role_credentials(
                accountId=self._sso_account_id,
                roleName=self._sso_role_name,
                accessToken=dados_token["accessToken"],
            )
        except ClientError as exc:
            codigo = exc.response["Error"]["Code"]
            raise RuntimeError(
                f"Token SSO rejeitado pela AWS (código={codigo}). "
                "Execute 'aws sso login --profile bastion' novamente."
            ) from exc

        role_creds = resp["roleCredentials"]
        expiration = datetime.fromtimestamp(role_creds["expiration"] / 1000, tz=timezone.utc)

        creds = Credenciais(
            access_key_id=role_creds["accessKeyId"],
            secret_access_key=role_creds["secretAccessKey"],
            session_token=role_creds["sessionToken"],
            expiration=expiration,
        )
        logger.info("Credenciais SSO obtidas | expira_em=%.0fs", creds.expira_em_segundos)
        return creds

    # ── AssumeRole ─────────────────────────────────────────────────────────────

    def _executar_assume_role(self, role_arn: str) -> Credenciais:
        """Executa sts:AssumeRole usando credenciais base SSO."""
        base = self._obter_credenciais_base()
        logger.info("Executando AssumeRole | arn=%s", role_arn)

        cliente_sts = boto3.client("sts", region_name=self._regiao_padrao, **base.para_boto3())
        try:
            resp = cliente_sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=self._nome_sessao,
                DurationSeconds=self._duracao_sessao,
            )
        except ClientError as exc:
            codigo = exc.response["Error"]["Code"]
            logger.error("AssumeRole falhou | role=%s | código=%s", role_arn, codigo)
            if codigo == "AccessDenied":
                raise PermissionError(
                    f"Acesso negado ao assumir a role '{role_arn}'. "
                    "Verifique a trust policy da role."
                ) from exc
            raise

        sts_creds = resp["Credentials"]
        creds = Credenciais(
            access_key_id=sts_creds["AccessKeyId"],
            secret_access_key=sts_creds["SecretAccessKey"],
            session_token=sts_creds["SessionToken"],
            expiration=sts_creds["Expiration"],
            assumed_role_arn=resp["AssumedRoleUser"]["Arn"],
        )
        logger.info("AssumeRole bem-sucedido | role=%s | expira_em=%.0fs", role_arn, creds.expira_em_segundos)
        return creds

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _obter_ou_renovar(self, chave: str, buscador) -> Credenciais:
        """Retorna credenciais do cache ou invoca buscador para renovar. Thread-safe."""
        with self._lock:
            cached = self._cache.get(chave)
            if cached and cached.validas:
                logger.debug("Usando credenciais em cache | chave=%s | expira_em=%.0fs", chave, cached.expira_em_segundos)
                return cached
            if cached:
                logger.info("Credenciais próximas da expiração. Renovando | chave=%s", chave)

        novas = buscador()

        with self._lock:
            self._cache[chave] = novas
        return novas
