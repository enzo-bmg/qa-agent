import os
import functools
import boto3
from strands.models.bedrock import BedrockModel

# ⚠️ DEV LOCAL APENAS — contorno de SSL do proxy do banco (Netskope).
# O time de rede do BMG não fornece o CA bundle (.pem). O Henrique Romão (BMG)
# orientou usar verify=False no boto3 EXCLUSIVAMENTE para o ambiente local de dev.
# NUNCA habilitar em produção — em prod a flag deve ficar ausente/false, mantendo
# a validação SSL normal.
# Ativado só quando DEV_INSECURE_SSL=true (definido no .env.local, que é gitignored).
_DEV_INSECURE_SSL = os.getenv("DEV_INSECURE_SSL", "false").lower() == "true"

_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
_REGION = os.getenv("AWS_REGION", "us-east-1")


def _insecure_session() -> boto3.Session:
    """boto3.Session cujo .client() sempre usa verify=False.

    O BedrockModel do Strands cria o cliente internamente a partir da session
    (não aceita um client pronto), então sobrescrevemos o .client() da session
    para injetar verify=False. Usado só em dev local atrás do proxy.
    """
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = boto3.Session(region_name=_REGION)
    original_client = session.client

    @functools.wraps(original_client)
    def client_no_verify(*args, **kwargs):
        kwargs.setdefault("verify", False)
        return original_client(*args, **kwargs)

    session.client = client_no_verify
    return session


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials.

    Em dev local atrás do proxy do banco (DEV_INSECURE_SSL=true), usa uma
    boto session com verify=False para contornar o SSL inspection do Netskope.
    Em produção (flag ausente/false), usa o comportamento padrão com validação
    SSL normal.
    """
    if _DEV_INSECURE_SSL:
        return BedrockModel(model_id=_MODEL_ID, boto_session=_insecure_session())

    return BedrockModel(model_id=_MODEL_ID, region_name=_REGION)
