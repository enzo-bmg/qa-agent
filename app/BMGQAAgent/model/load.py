import os
import logging
from pathlib import Path
from typing import Any

import boto3
from dotenv import dotenv_values, load_dotenv
from strands.models.bedrock import BedrockModel

logger = logging.getLogger(__name__)


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.is_file():
        return

    values = dotenv_values(env_path)
    if os.getenv("LOCAL_DEV", values.get("LOCAL_DEV")) != "1":
        return

    load_dotenv(dotenv_path=env_path, override=False)


_load_local_env()

# Modelo padrão — pode ser sobrescrito por env (útil se o BMG só habilitar
# outra versão do Claude no Model Access).
DEFAULT_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"


def _load_bedrock_model(**model_config: Any) -> BedrockModel:
    session_config: dict[str, Any] = {"region_name": AWS_REGION}
    if AWS_PROFILE:
        session_config["profile_name"] = AWS_PROFILE

    session = boto3.Session(**session_config)
    model = BedrockModel(boto_session=session, **model_config)

    if not VERIFY_SSL:
        logger.warning("Verificação SSL desativada para bedrock-runtime; use apenas em ambiente local/teste.")
    model.client = session.client(
        service_name="bedrock-runtime",
        region_name=model.client.meta.region_name,
        config=model.client.meta.config,
        verify=VERIFY_SSL,
    )

    return model


def load_model() -> BedrockModel:
    """Carrega o cliente do Bedrock usando credenciais IAM.

    O Guardrail é plugado diretamente na config do modelo. Assim toda
    invocação passa pelo filtro de PII/compliance sem precisar invocar o
    guardrail separadamente. `guardrail_redact_input=True` anonimiza PII no
    input — comportamento exigido para dado bancário.

    Se `GUARDRAIL_ID` não estiver configurado, o modelo sobe SEM guardrail
    (para não travar o dev local de quem não configurou), mas registra um
    aviso — rodar sem guardrail com dado real é risco de compliance.
    """
    guardrail_id = os.getenv("GUARDRAIL_ID")

    if not guardrail_id:
        logger.warning(
            "GUARDRAIL_ID não configurado — modelo carregado SEM guardrail. "
            "NÃO usar com dado real (PII/compliance)."
        )
        return _load_bedrock_model(model_id=DEFAULT_MODEL_ID)

    guardrail_version = os.getenv("GUARDRAIL_VERSION", "DRAFT")
    # Redação de input ligada por padrão (anonimiza PII). Output não é redigido
    # por padrão para o QA ver o cenário completo — ajustável por env.
    redact_input = os.getenv("GUARDRAIL_REDACT_INPUT", "true").lower() == "true"
    redact_output = os.getenv("GUARDRAIL_REDACT_OUTPUT", "false").lower() == "true"

    logger.info(
        "Guardrail plugado no modelo: id=%s version=%s redact_input=%s redact_output=%s",
        guardrail_id, guardrail_version, redact_input, redact_output,
    )

    return _load_bedrock_model(
        model_id=DEFAULT_MODEL_ID,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_redact_input=redact_input,
        guardrail_redact_output=redact_output,
    )
