@echo off
chcp 65001 >nul
echo ============================================================
echo  Configuracao inicial — Agente Orquestrador
echo ============================================================
echo.

REM ── 1. Instalar dependencias ─────────────────────────────────
echo [1/2] Instalando dependencias Python...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERRO: Falha ao instalar dependencias. Verifique se o Python e pip estao no PATH.
    pause
    exit /b 1
)
echo Dependencias instaladas com sucesso.
echo.

REM ── 2. Criar .env a partir do exemplo ────────────────────────
if exist .env (
    echo [2/2] Arquivo .env ja existe. Pulando copia.
) else (
    echo [2/2] Criando arquivo .env a partir do .env.example...
    copy .env.example .env >nul
    echo Arquivo .env criado com sucesso.
)
echo.

REM ── 3. Instrucoes para o usuario ─────────────────────────────
echo ============================================================
echo  PROXIMOS PASSOS
echo ============================================================
echo.
echo  1. Abra o arquivo .env e preencha TODAS as variaveis:
echo.
echo     - STACKSPOT_REALM        : realm da sua conta StackSpot
echo     - STACKSPOT_CLIENT_ID    : client ID da credencial de servico
echo     - STACKSPOT_CLIENT_SECRET: client secret
echo     - STACKSPOT_AGENT_ID     : ID do agente configurado
echo     - AWS_SSO_START_URL      : URL do portal SSO da sua org
echo     - AWS_SSO_REGION         : regiao do SSO (ex: us-east-1)
echo     - AWS_SSO_ACCOUNT_ID     : ID da conta bastion
echo     - AWS_SSO_ROLE_NAME      : nome da role na conta bastion
echo     - AWS_ROLE_ARN_TEMPLATE  : ARN template das contas-alvo
echo     - CLOUDTRAIL_QUERY       : query SQL do CloudTrail
echo.
echo  2. Faca login no AWS SSO com o perfil bastion:
echo.
echo        aws sso login --profile bastion
echo.
echo  3. Execute o orquestrador:
echo.
echo        python main.py exemplo.csv
echo.
echo ============================================================
pause
