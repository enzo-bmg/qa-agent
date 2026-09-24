import os
import logging

from strands.models.bedrock import BedrockModel

logger = logging.getLogger(__name__)

# Modelo padrão — pode ser sobrescrito por env (útil se o BMG só habilitar
# outra versão do Claude no Model Access).
DEFAULT_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
)


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
        return BedrockModel(model_id=DEFAULT_MODEL_ID)

    guardrail_version = os.getenv("GUARDRAIL_VERSION", "DRAFT")
    # Redação de input ligada por padrão (anonimiza PII). Output não é redigido
    # por padrão para o QA ver o cenário completo — ajustável por env.
    redact_input = os.getenv("GUARDRAIL_REDACT_INPUT", "true").lower() == "true"
    redact_output = os.getenv("GUARDRAIL_REDACT_OUTPUT", "false").lower() == "true"

    logger.info(
        "Guardrail plugado no modelo: id=%s version=%s redact_input=%s redact_output=%s",
        guardrail_id, guardrail_version, redact_input, redact_output,
    )

    return BedrockModel(
        model_id=DEFAULT_MODEL_ID,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_redact_input=redact_input,
        guardrail_redact_output=redact_output,
    )
