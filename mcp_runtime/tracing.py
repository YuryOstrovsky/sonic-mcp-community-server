import uuid

def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"

def new_correlation_id() -> str:
    return f"corr-{uuid.uuid4().hex[:8]}"

