"""Audit trail services — one place that knows how to write audit events."""

import logging

logger = logging.getLogger(__name__)


def record_audit(request, *, organization=None, action: str, target=None, metadata=None):
    """Record a domain audit event. Never raises — auditing must not take
    the business transaction down; failures are logged instead.

    Callers pass the request for actor/IP; services without a request
    context (Celery tasks) pass user/organization explicitly.
    """
    from audit.models import AuditEvent

    user = getattr(request, "user", None)
    ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR")
        if request is not None
        else None
    ) or None
    target_type = target.__class__.__name__ if target is not None else None
    target_id = str(getattr(target, "pk", "")) or None

    try:
        return AuditEvent.objects.create(
            organization=organization,
            user=user if getattr(user, "is_authenticated", False) else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - defensive by design
        logger.exception("Failed to record audit event %s", action)
        return None
