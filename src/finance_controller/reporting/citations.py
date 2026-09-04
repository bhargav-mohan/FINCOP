from __future__ import annotations

from finance_controller.models import ReconException


def citation_tokens(exception: ReconException) -> list[str]:
    """Instance tokens an explanation must cite: refs, amounts, engine reason."""
    tokens: list[str] = []
    for ref in exception.references:
        if ref and len(ref) >= 3:
            tokens.append(ref)
    for rec_id, amount in exception.amounts.items():
        tokens.append(str(amount))
        if rec_id and len(rec_id) >= 3:
            tokens.append(rec_id)
    reason = (exception.reason or "").strip()
    if reason:
        tokens.append(reason)
    return tokens


def cites_instance(text: str, exception: ReconException) -> bool:
    hay = (text or "").lower()
    if not hay:
        return False
    return any(token.lower() in hay for token in citation_tokens(exception))
