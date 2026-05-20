import boto3
import json
import os
from datetime import datetime

# ============================================================================
# Configuração – ajuste o bucket S3 de saída
# ============================================================================
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "meu-bucket-auditoria")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "glue-credenciais/")

def get_current_credentials():
    """
    Obtém as credenciais da role que está executando o job Glue.
    Sem chamar AssumeRole – apenas lê as credenciais da sessão boto3.
    """
    session = boto3.Session()
    credentials = session.get_credentials()
    
    # Se estiver usando credenciais temporárias (padrão no Glue)
    if hasattr(credentials, 'access_key') and hasattr(credentials, 'secret_key'):
        cred_data = {
            "AccessKeyId": credentials.access_key,
            "SecretAccessKey": credentials.secret_key,
            "SessionToken": credentials.token,  # pode ser None se for IAM user, mas no Glue sempre há token
            "Expiration": None  # infelizmente a biblioteca boto3 não expõe a data de expiração diretamente
        }
    else:
        # Fallback: usar STS para obter informações (as credenciais em si não são expostas)
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        cred_data = {
            "Note": "As credenciais atuais são gerenciadas pelo serviço Glue. Não foi possível extrair AccessKey/SecretKey diretamente.",
            "IdentityArn": identity['Arn']
        }
    return cred_data

def assume_own_role():
    """
    (Opcional) Faz AssumeRole da própria role de execução.
    Requer que a trust policy da role permita `sts:AssumeRole` para ela mesma.
    """
    sts = boto3.client('sts')
    own_arn = sts.get_caller_identity()['Arn']
    
    try:
        response = sts.assume_role(
            RoleArn=own_arn,
            RoleSessionName=f"AutoAssume-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            DurationSeconds=3600
        )
        creds = response['Credentials']
        return {
            "AccessKeyId": creds['AccessKeyId'],
            "SecretAccessKey": creds['SecretAccessKey'],
            "SessionToken": creds['SessionToken'],
            "Expiration": creds['Expiration'].isoformat(),
            "AssumedRoleArn": own_arn,
            "Method": "AssumeRole (auto-assume)"
        }
    except Exception as e:
        return {
            "Error": f"Auto-assume falhou. Verifique se a role tem trust policy para si mesma: {str(e)}",
            "AttemptedRoleArn": own_arn
        }

def write_to_s3(data, filename_suffix):
    """Grava os dados como JSON no bucket S3."""
    s3 = boto3.client('s3')
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    key = f"{OUTPUT_PREFIX.rstrip('/')}/credenciais_{filename_suffix}_{timestamp}.json"
    
    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2, default=str),
        ContentType='application/json'
    )
    print(f"Arquivo salvo: s3://{OUTPUT_BUCKET}/{key}")

# ============================================================================
# Execução principal
# ============================================================================
if __name__ == "__main__":
    print("=== Capturando credenciais atuais da role de execução do Glue ===")
    current = get_current_credentials()
    write_to_s3(current, "current")
    
    print("=== Testando auto-assume da própria role (opcional) ===")
    assumed = assume_own_role()
    write_to_s3(assumed, "auto_assumed")
    
    print("Script concluído. Verifique seu bucket S3.")
