from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import PaymentRecord, StripeEvent, Subscription


PLAN_CONFIG = {
    "base": {"name": "Muellima Base", "amount": 1999},
    "premium": {"name": "Muellima Premium", "amount": 4500},
}


def _configure_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise ValueError("STRIPE_SECRET_KEY non configurata")
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(user, plan: str, success_url: str, cancel_url: str):
    if plan not in PLAN_CONFIG:
        raise ValueError("Piano non valido")
    _configure_stripe()
    local_subscription, _ = Subscription.objects.get_or_create(user=user)
    plan_config = PLAN_CONFIG[plan]
    customer_args = (
        {"customer": local_subscription.stripe_customer_id}
        if local_subscription.stripe_customer_id
        else {"customer_email": user.email}
    )
    return stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": plan_config["amount"],
                "recurring": {"interval": "month"},
                "product_data": {"name": plan_config["name"]},
            },
            "quantity": 1,
        }],
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id), "plan": plan},
        subscription_data={"metadata": {"user_id": str(user.id), "plan": plan}},
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        **customer_args,
    )


def create_portal_session(user, return_url: str):
    _configure_stripe()
    local_subscription = Subscription.objects.get(user=user)
    if not local_subscription.stripe_customer_id:
        raise ValueError("Cliente Stripe non disponibile")
    return stripe.billing_portal.Session.create(
        customer=local_subscription.stripe_customer_id,
        return_url=return_url,
    )


def construct_webhook_event(payload: bytes, signature: str):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET non configurata")
    return stripe.Webhook.construct_event(
        payload,
        signature,
        settings.STRIPE_WEBHOOK_SECRET,
    )


def _timestamp(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)


def _subscription_id(obj) -> str:
    subscription_id = obj.get("subscription")
    if subscription_id:
        return subscription_id
    parent = obj.get("parent") or {}
    details = parent.get("subscription_details") or {}
    return details.get("subscription") or ""


def _find_user(obj):
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id") or obj.get("client_reference_id")
    if user_id:
        return get_user_model().objects.filter(id=user_id).first()
    customer_id = obj.get("customer")
    subscription_id = obj.get("id") if obj.get("object") == "subscription" else _subscription_id(obj)
    local = Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
    if not local and customer_id:
        local = Subscription.objects.filter(stripe_customer_id=customer_id).first()
    return local.user if local else None


def _sync_subscription(obj, *, checkout: bool = False) -> None:
    user = _find_user(obj)
    if not user:
        return
    local, _ = Subscription.objects.get_or_create(user=user)
    metadata = obj.get("metadata") or {}
    if metadata.get("plan") in PLAN_CONFIG:
        local.plan = metadata["plan"]
    local.stripe_customer_id = obj.get("customer") or local.stripe_customer_id
    if checkout:
        local.stripe_subscription_id = obj.get("subscription") or local.stripe_subscription_id
        local.status = "active" if obj.get("payment_status") in {"paid", "no_payment_required"} else "incomplete"
    else:
        local.stripe_subscription_id = obj.get("id") or local.stripe_subscription_id
        local.status = obj.get("status") or local.status
        period_end = obj.get("current_period_end")
        if not period_end:
            items = ((obj.get("items") or {}).get("data") or [])
            period_end = items[0].get("current_period_end") if items else None
        local.current_period_end = _timestamp(period_end)
    local.save()


def _record_invoice(obj, status: str) -> None:
    user = _find_user(obj)
    invoice_id = obj.get("id")
    if not invoice_id:
        return
    PaymentRecord.objects.update_or_create(
        stripe_invoice_id=invoice_id,
        defaults={
            "user": user,
            "amount_cents": max(0, int(obj.get("amount_paid") or obj.get("amount_due") or 0)),
            "currency": (obj.get("currency") or "eur")[:3],
            "status": status,
            "occurred_at": _timestamp(obj.get("created")) or timezone.now(),
        },
    )
    if user:
        local, _ = Subscription.objects.get_or_create(user=user)
        local.status = "active" if status == "paid" else "past_due"
        local.save(update_fields=["status", "updated_at"])


@transaction.atomic
def process_webhook_event(event) -> bool:
    event_id = event["id"]
    event_type = event["type"]
    _, created = StripeEvent.objects.get_or_create(
        stripe_event_id=event_id,
        defaults={"event_type": event_type},
    )
    if not created:
        return False

    obj = event["data"]["object"]
    if event_type == "checkout.session.completed":
        _sync_subscription(obj, checkout=True)
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        _sync_subscription(obj)
    elif event_type == "customer.subscription.deleted":
        _sync_subscription(obj)
    elif event_type == "invoice.paid":
        _record_invoice(obj, "paid")
    elif event_type == "invoice.payment_failed":
        _record_invoice(obj, "failed")
    return True
