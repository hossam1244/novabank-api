"""Celery tasks — settlement and outbound notifications."""

import logging

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

ORG_GROUP = "org.{org_id}"


def payment_payload(payment) -> dict:
    return {
        "type": "payment.updated",
        "payment": {
            "id": str(payment.id),
            "kind": payment.kind,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "beneficiary_name": payment.beneficiary_name,
            "reference": payment.reference,
            "status": payment.status,
            "settled_at": payment.settled_at.isoformat() if payment.settled_at else None,
        },
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=2)
def notify_payment_update(self, payment_id):
    """Push a payment status change to the organization's WebSocket group.

    Notifications are best-effort: a broker hiccup retries up to three times
    and then gives up with an error log — it must never take the payment
    flow down.
    """
    from banking.models import Payment

    layer = get_channel_layer()
    try:
        payment = Payment.objects.select_related("organization", "account").get(pk=payment_id)
        async_to_sync(layer.group_send)(
            ORG_GROUP.format(org_id=payment.organization_id),
            payment_payload(payment),
        )
    except Payment.DoesNotExist:
        logger.warning("notify_payment_update: payment %s vanished", payment_id)
    except Exception as exc:  # transient broker/channel issues → retry
        if self.request.retries < self.max_retries:
            logger.warning("channel send failed for %s (retrying): %s", payment_id, exc)
            raise self.retry(exc=exc) from exc
        logger.error("channel send gave up for %s: %s", payment_id, exc)


@shared_task
def send_payment_email(payment_id, user_id=None):
    """Email the payment creator (console backend in dev; SMTP in prod)."""
    from banking.models import Payment

    payment = Payment.objects.select_related("organization").get(pk=payment_id)
    recipient = None
    if user_id is not None:
        recipient = get_user_model().objects.filter(pk=user_id).first()
    elif payment.created_by_id:
        recipient = payment.created_by

    if recipient is None:
        logger.info("no recipient for payment %s email", payment_id)
        return

    from django.core.mail import send_mail

    send_mail(
        subject=f"[NovaBank] Payment {payment.status}: {payment.amount} {payment.currency}",
        message=(
            f"Your payment to {payment.beneficiary_name or 'external beneficiary'}\n"
            f"Amount:   {payment.amount} {payment.currency}\n"
            f"Reference: {payment.reference or '-'}\n"
            f"Status:   {payment.status}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL
        if hasattr(settings, "DEFAULT_FROM_EMAIL")
        else "noreply@novabank.example",
        recipient_list=[recipient.email],
        fail_silently=False,
    )
    return f"emailed {recipient.email}"


# Imported by banking.services — keep the alias so the import path reads clearly.
from banking.services import settle_payment as _settle_payment  # noqa: E402


@shared_task(name="novabank.settle_payment")
def settle_payment(payment_id):
    """Celery entrypoint that runs the domain settlement service."""
    return _settle_payment(payment_id)
