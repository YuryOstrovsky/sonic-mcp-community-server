# mcp_runtime/explain_contract.py

EXPLANATION_CONTRACT_VERSION = "1.0"

REQUIRED_TOP_LEVEL_FIELDS = {
    "version": str,
    "status": str,
    "summary": dict,
    "steps": list,
    "confidence": float,
    "reasons": list,
}

SUMMARY_REQUIRED_FIELDS = {
    "steps_executed": int,
    "mutations": int,
    "rollbacks": int,
    "final_status": str,
}


class ExplanationContractError(Exception):
    pass


def validate_explanation_contract(explanation: dict):
    # Top-level fields
    for field, field_type in REQUIRED_TOP_LEVEL_FIELDS.items():
        if field not in explanation:
            raise ExplanationContractError(f"Missing field: '{field}'")
        if not isinstance(explanation[field], field_type):
            raise ExplanationContractError(
                f"Field '{field}' must be {field_type.__name__}"
            )

    # Version check
    if explanation["version"] != EXPLANATION_CONTRACT_VERSION:
        raise ExplanationContractError(
            f"Unsupported explanation version: {explanation['version']}"
        )

    # Summary fields
    summary = explanation["summary"]
    for field, field_type in SUMMARY_REQUIRED_FIELDS.items():
        if field not in summary:
            raise ExplanationContractError(
                f"Summary missing field: '{field}'"
            )
        if not isinstance(summary[field], field_type):
            raise ExplanationContractError(
                f"Summary field '{field}' must be {field_type.__name__}"
            )

    return True

