"""
LoksewaAI — NCM Phase 13 Automatic Courier Dispatch Service
Orchestrates idempotent, reliable, and auditable courier shipment creation
immediately after admin payment approval.
"""

import logging
import threading
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from marketplace.models import (
    Order,
    CourierShipment,
    OrderStatusHistory,
    CODRemittance,
    NCMDispatchJob,
)
from marketplace.ncm_service import (
    NCMService,
    NCMError,
    NCMConnectionError,
    NCMAPIError,
    NCMValidationError,
)

logger = logging.getLogger(__name__)


def validate_ncm_branch_strictly(branch_name_or_code: str, service: NCMService) -> Optional[str]:
    """
    Validates the destination branch strictly against active NCM branches.
    Returns the canonical branch name or None.
    NEVER silently substitutes or guesses a different branch.
    """
    if not branch_name_or_code:
        return None
    target = str(branch_name_or_code).strip().lower()
    try:
        branches = service.get_branches()
        for b in branches:
            name = str(b.get('name') or '').strip()
            code = str(b.get('code') or b.get('pk') or b.get('id') or '').strip().lower()
            if name.lower() == target or code == target:
                return name
        return None
    except Exception as exc:
        logger.warning("Error fetching branches while validating NCM branch '%s': %s", branch_name_or_code, exc)
        return None


def validate_order_for_ncm_dispatch(order: Order, service: NCMService) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Validates that an order is fully eligible for NCM courier dispatch.

    Strict Business Rules:
    1. Order status must be CONFIRMED or PROCESSING.
    2. If COD: order.payment_status must be PARTIALLY_PAID (15% advance verified).
    3. If PREPAID: order.payment_status must be PAID (100% full payment verified).
    4. Must not already have an active CourierShipment.
    5. Order must have a valid persisted destination branch from the student snapshot.
       (Never silently substitute a different branch).
    6. Must have complete recipient shipping address and contact info.

    Returns:
        (is_valid: bool, error_message: Optional[str], ncm_payload: Optional[dict])
    """
    # 1. Status verification
    if order.status not in ['CONFIRMED', 'PROCESSING']:
        return False, f"Order #{order.id} is in status '{order.status}'. Only CONFIRMED or PROCESSING orders can be dispatched.", None

    if order.status in ['CANCELLED', 'REFUNDED', 'DELIVERED', 'ON_HOLD']:
        return False, f"Order #{order.id} has terminal or hold status '{order.status}' and cannot be dispatched.", None

    # 2. Payment verification
    if order.is_cod:
        if order.payment_status != 'PARTIALLY_PAID':
            return False, f"Cannot dispatch COD order #{order.id} with payment status '{order.payment_status}'. 15% advance payment must be verified first.", None
        # Check advance amount
        if order.cod_advance_paid < order.cod_advance_required and order.cod_advance_paid <= 0:
            return False, f"COD advance payment (Rs. {order.cod_advance_paid}) does not meet the required Rs. {order.cod_advance_required}.", None
    else:
        if order.payment_status != 'PAID':
            return False, f"Cannot dispatch prepaid order #{order.id} with payment status '{order.payment_status}'. Full payment must be verified first.", None

    # 3. Idempotency check: prevent duplicate shipment
    if hasattr(order, 'courier_shipment') and order.courier_shipment:
        return False, f"Shipment already exists for Order #{order.id} (NCM Order ID: {order.courier_shipment.ncm_order_id}).", None

    if order.ncm_dispatch_status == 'CREATED':
        return False, f"Order #{order.id} already marked CREATED in NCM.", None

    # 4. Resolve persisted destination branch from shipping_address_snapshot
    snapshot = order.shipping_address_snapshot or {}
    dest_branch = (snapshot.get('ncm_destination_branch') or '').strip()
    if not dest_branch:
        return False, f"Order #{order.id} is missing a persisted NCM destination branch in shipping address snapshot.", None

    # Validate destination branch against NCM active branches strictly
    valid_branch = validate_ncm_branch_strictly(dest_branch, service)
    if not valid_branch:
        return False, f"Persisted destination branch '{dest_branch}' is not a recognized NCM branch.", None

    # 5. Delivery details
    name = (snapshot.get('full_name') or order.student.get_full_name() or order.student.username).strip()
    phone = (snapshot.get('phone_number') or order.contact_number).strip()
    phone2 = (snapshot.get('phone2') or '').strip()
    instruction = (snapshot.get('delivery_note') or '').strip()
    delivery_type = (snapshot.get('ncm_delivery_type') or 'Door2Door').strip()

    address = (
        ", ".join(filter(None, [
            snapshot.get('tole_area'),
            f"Ward {snapshot.get('ward_number')}" if snapshot.get('ward_number') else "",
            snapshot.get('municipality'),
            snapshot.get('district'),
            snapshot.get('province'),
        ])) or order.shipping_address
    ).strip()

    if not name or not phone or not address:
        return False, "Customer name, phone number, and street address are required for courier dispatch.", None

    # 6. Package description & weight
    items = list(order.items.select_related('product').all())
    desc_parts = [f"{it.quantity}x {it.product.title}" for it in items[:3]]
    if len(items) > 3:
        desc_parts.append(f"+{len(items)-3} more items")
    package_description = ", ".join(desc_parts) or "Loksewa Study Material"

    weight = 1.0

    # 7. COD charge:
    # STRICT RULE: 15% advance was verified; NCM must collect remaining 85% balance.
    # For prepaid, NCM must collect exactly 0.00.
    if order.is_cod:
        cod_charge = float(order.cod_remaining_balance)
    else:
        cod_charge = 0.0

    ncm_payload = {
        "name": name,
        "phone": phone,
        "phone2": phone2,
        "cod_charge": cod_charge,
        "address": address,
        "fbranch": service.default_origin_branch,
        "branch": valid_branch,
        "package": package_description[:250],
        "vref_id": f"ORD-{order.id}",
        "instruction": instruction[:250],
        "delivery_type": delivery_type,
        "weight": weight,
    }

    return True, None, ncm_payload


def _sync_dispatch_job(
    order_id: int,
    status: str,
    last_error: str = '',
    attempts: Optional[int] = None,
    next_retry_at: Optional[Any] = None,
) -> None:
    """Safely synchronizes durable NCMDispatchJob outbox record."""
    try:
        from marketplace.models import NCMDispatchJob
        job = NCMDispatchJob.objects.filter(order_id=order_id).order_by('-created_at').first()
        if not job:
            job = NCMDispatchJob.objects.create(order_id=order_id, status=status)
        job.status = status
        job.last_attempt_at = timezone.now()
        if last_error:
            job.last_error = last_error
        if attempts is not None:
            job.attempts = attempts
        if next_retry_at is not None:
            job.next_retry_at = next_retry_at
        job.save()
    except Exception as e:
        logger.debug("Failed to sync NCMDispatchJob for Order #%s: %s", order_id, e)


def execute_ncm_dispatch(
    order_id: int,
    force_retry: bool = False,
    admin_user=None,
    celery_task=None
) -> Dict[str, Any]:
    """
    Idempotently and reliably dispatches an order to Nepal Can Move (NCM).

    Protections:
    - select_for_update() row lock prevents concurrent dispatch calls.
    - Idempotency guard guarantees at most one active shipment per order.
    - Ambiguous timeout reconciliation via vref_id prevents blind duplicate creation.
    - If ambiguous and not reconciled, transitions to MANUAL_REVIEW_REQUIRED.
    - Confirmed transient network failures have bounded retries with exponential backoff.
    - Transitions order status to PROCESSING and creates CourierShipment on success.
    - Preserves COD payment rules (does NOT mark COD orders as fully PAID).
    """
    service = NCMService()
    if not service.is_configured():
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(pk=order_id).first()
            if order:
                order.ncm_dispatch_status = 'FAILED'
                order.ncm_dispatch_last_error = "NCM courier service is not configured (missing API credentials)."
                order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error'])
                _sync_dispatch_job(order_id, status='FAILED', last_error=order.ncm_dispatch_last_error)
        return {"status": "FAILED", "error": "NCM courier service is not configured."}

    # 1. Acquire row lock and verify eligibility
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_id).first()
        if not order:
            logger.error("Order #%s not found for NCM dispatch.", order_id)
            return {"status": "NOT_FOUND", "error": f"Order #{order_id} not found."}

        # Idempotency check 1: Already shipped
        if hasattr(order, 'courier_shipment') and order.courier_shipment:
            logger.info("Order #%s already has NCM shipment #%s. Skipping.", order_id, order.courier_shipment.ncm_order_id)
            if order.ncm_dispatch_status != 'CREATED':
                order.ncm_dispatch_status = 'CREATED'
                order.save(update_fields=['ncm_dispatch_status'])
            _sync_dispatch_job(order_id, status='COMPLETED')
            return {
                "status": "ALREADY_DISPATCHED",
                "ncm_order_id": order.courier_shipment.ncm_order_id,
                "tracking_id": order.courier_shipment.tracking_id,
            }

        # Idempotency check 2: Ambiguous timeout pending manual review
        if order.ncm_dispatch_status == 'MANUAL_REVIEW_REQUIRED' and not force_retry:
            logger.warning("Order #%s is in MANUAL_REVIEW_REQUIRED. Attempting reconciliation lookup before retrying.", order_id)
            # Try reconciliation lookup
            reconciled = service.lookup_order_by_vref(f"ORD-{order.id}")
            if reconciled and reconciled.get("orderid"):
                return _persist_successful_ncm_shipment(
                    order=order,
                    api_res={
                        "success": True,
                        "ncm_order_id": str(reconciled["orderid"]),
                        "delivery_charge": float(reconciled.get("delivery_charge", 0.0)),
                        "cod_charge": float(reconciled.get("cod_charge", 0.0)),
                        "delivery_type": reconciled.get("delivery_type", "Door2Door"),
                        "raw_response": reconciled.get("raw_response", reconciled),
                    },
                    valid_branch=reconciled.get("branch") or order.shipping_address_snapshot.get("ncm_destination_branch"),
                    delivery_type=reconciled.get("delivery_type", "Door2Door"),
                    package_description="Loksewa Study Material",
                    weight=1.0,
                    service=service,
                    admin_user=admin_user,
                    is_reconciled=True,
                )
            else:
                _sync_dispatch_job(order_id, status='MANUAL_REVIEW_REQUIRED', last_error=order.ncm_dispatch_last_error)
                return {
                    "status": "MANUAL_REVIEW_REQUIRED",
                    "error": order.ncm_dispatch_last_error or "Order requires manual admin review after ambiguous timeout.",
                }

        # Idempotency check 3: Already in CREATING state by another process
        if order.ncm_dispatch_status == 'CREATING' and not force_retry:
            # If it's been in CREATING for less than 60 seconds, allow active process to finish
            if order.ncm_dispatch_last_attempt_at and (timezone.now() - order.ncm_dispatch_last_attempt_at).total_seconds() < 60:
                logger.info("Order #%s is currently being created by another worker. Skipping concurrent attempt.", order_id)
                return {"status": "IN_PROGRESS"}

        # Validate eligibility
        is_valid, err_msg, ncm_payload = validate_order_for_ncm_dispatch(order, service)
        if not is_valid:
            logger.warning("Order #%s failed dispatch validation: %s", order_id, err_msg)
            order.ncm_dispatch_status = 'FAILED'
            order.ncm_dispatch_last_error = err_msg or "Validation failed."
            order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error'])
            _sync_dispatch_job(order_id, status='FAILED', last_error=err_msg or "Validation failed.")
            return {"status": "VALIDATION_FAILED", "error": err_msg}

        # Transition to CREATING
        order.ncm_dispatch_status = 'CREATING'
        order.ncm_dispatch_last_attempt_at = timezone.now()
        order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_attempt_at'])
        _sync_dispatch_job(order_id, status='PROCESSING')

    # 2. Call external NCM API (outside database transaction to keep lock short)
    valid_branch = ncm_payload["branch"]
    delivery_type = ncm_payload["delivery_type"]
    package_description = ncm_payload["package"]
    weight = ncm_payload["weight"]

    try:
        api_res = service.create_order(ncm_payload)
    except NCMConnectionError as exc:
        logger.error("NCM shipment creation connection error for Order #%s: %s (ambiguous=%s)", order_id, exc, exc.is_ambiguous)

        if exc.is_ambiguous:
            # The HTTP request was sent, but response timed out.
            # CRITICAL RULE: DO NOT BLINDLY RETRY TO AVOID DUPLICATE SHIPMENT.
            logger.info("Attempting automatic reconciliation lookup for Order #%s (ref ORD-%s)...", order_id, order_id)
            reconciled = service.lookup_order_by_vref(f"ORD-{order_id}")
            if reconciled and reconciled.get("orderid"):
                logger.info("Successfully reconciled Order #%s with NCM Order ID %s!", order_id, reconciled["orderid"])
                return _persist_successful_ncm_shipment(
                    order_id=order_id,
                    api_res={
                        "success": True,
                        "ncm_order_id": str(reconciled["orderid"]),
                        "delivery_charge": float(reconciled.get("delivery_charge", 0.0)),
                        "cod_charge": float(reconciled.get("cod_charge", ncm_payload["cod_charge"])),
                        "delivery_type": reconciled.get("delivery_type", delivery_type),
                        "raw_response": reconciled.get("raw_response", reconciled),
                    },
                    valid_branch=valid_branch,
                    delivery_type=delivery_type,
                    package_description=package_description,
                    weight=weight,
                    service=service,
                    admin_user=admin_user,
                    is_reconciled=True,
                )
            else:
                # Could not reconcile. Move to MANUAL_REVIEW_REQUIRED.
                with transaction.atomic():
                    order = Order.objects.select_for_update().get(pk=order_id)
                    order.ncm_dispatch_status = 'MANUAL_REVIEW_REQUIRED'
                    order.ncm_dispatch_last_error = (
                        f"Ambiguous network timeout contacting NCM: {str(exc)}. "
                        "The order may have been created in the courier portal. "
                        "Do not blindly retry without checking NCM portal or reconciling."
                    )
                    order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error'])
                    _sync_dispatch_job(order_id, status='MANUAL_REVIEW_REQUIRED', last_error=order.ncm_dispatch_last_error)
                return {"status": "MANUAL_REVIEW_REQUIRED", "error": order.ncm_dispatch_last_error}
        else:
            # Confirmed transient connection failure before sending payload
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)
                order.ncm_dispatch_status = 'FAILED'
                order.ncm_dispatch_attempts += 1
                order.ncm_dispatch_last_error = f"Transient connection failure: {str(exc)}"
                if order.ncm_dispatch_attempts < 3:
                    backoff_secs = 60 * (2 ** (order.ncm_dispatch_attempts - 1))
                    order.ncm_dispatch_next_retry = timezone.now() + timedelta(seconds=backoff_secs)
                else:
                    order.ncm_dispatch_next_retry = None
                order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_attempts', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry'])
                _sync_dispatch_job(
                    order_id,
                    status='FAILED',
                    last_error=order.ncm_dispatch_last_error,
                    attempts=order.ncm_dispatch_attempts,
                    next_retry_at=order.ncm_dispatch_next_retry,
                )

            # Bounded Celery retry if running within Celery worker
            if celery_task and order.ncm_dispatch_attempts < 3:
                try:
                    celery_task.retry(countdown=backoff_secs, exc=exc)
                except Exception:
                    pass

            return {"status": "FAILED", "error": str(exc), "retry_scheduled": order.ncm_dispatch_attempts < 3}

    except (NCMAPIError, NCMValidationError, NCMError) as exc:
        logger.error("NCM shipment creation API error for Order #%s: %s", order_id, exc)
        err_str = str(exc)
        if "401" in err_str or "Invalid token" in err_str:
            last_error = "NCM API authentication failed (401: Invalid Token). Please update NCM_API_TOKEN in Render or Admin Courier Settings."
        else:
            last_error = f"NCM API error: {err_str}"
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order_id)
            order.ncm_dispatch_status = 'FAILED'
            order.ncm_dispatch_attempts += 1
            order.ncm_dispatch_last_error = last_error
            order.ncm_dispatch_next_retry = None  # API errors are usually deterministic, do not auto retry
            order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_attempts', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry'])
            _sync_dispatch_job(
                order_id,
                status='FAILED',
                last_error=last_error,
                attempts=order.ncm_dispatch_attempts,
                next_retry_at=None,
            )
        return {"status": "FAILED", "error": last_error}

    # 3. Successful dispatch from NCM API
    return _persist_successful_ncm_shipment(
        order_id=order_id,
        api_res=api_res,
        valid_branch=valid_branch,
        delivery_type=delivery_type,
        package_description=package_description,
        weight=weight,
        service=service,
        admin_user=admin_user,
        is_reconciled=False,
    )


def _persist_successful_ncm_shipment(
    api_res: Dict[str, Any],
    valid_branch: str,
    delivery_type: str,
    package_description: str,
    weight: float,
    service: NCMService,
    order: Optional[Order] = None,
    order_id: Optional[int] = None,
    admin_user=None,
    is_reconciled: bool = False,
) -> Dict[str, Any]:
    """
    Persists successful NCM shipment creation inside a transaction.
    Guarantees:
    - OneToOne relationship on Order.courier_shipment
    - Transition order status to PROCESSING
    - Persists NCM order ID, tracking ID, raw response
    - Creates CODRemittance for COD orders
    - Preserves COD payment rules (never auto-marks PAID)
    - Dispatches student notification
    """
    target_pk = order.pk if order else order_id
    ncm_order_id = str(api_res["ncm_order_id"]).strip()
    tracking_id = str(api_res.get("tracking_id") or ncm_order_id).strip()
    delivery_charge = Decimal(str(api_res.get("delivery_charge", 0.0)))
    cod_charge = Decimal(str(api_res.get("cod_charge", 0.0)))

    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=target_pk)

        # Idempotency check inside transaction
        if hasattr(locked_order, 'courier_shipment') and locked_order.courier_shipment:
            logger.info("Order #%s already has shipment inside persist block. Skipping.", target_pk)
            locked_order.ncm_dispatch_status = 'CREATED'
            locked_order.save(update_fields=['ncm_dispatch_status'])
            return {
                "status": "ALREADY_DISPATCHED",
                "ncm_order_id": locked_order.courier_shipment.ncm_order_id,
                "tracking_id": locked_order.courier_shipment.tracking_id,
            }

        quoted_charge = Decimal(str(locked_order.delivery_fee or "0.00"))

        status_note = "Automatically dispatched after admin payment approval"
        if is_reconciled:
            status_note = "Reconciled with NCM shipment record after timeout"
        elif admin_user:
            status_note = f"Dispatched by admin {admin_user.username}"

        shipment = CourierShipment.objects.create(
            order=locked_order,
            provider='NCM',
            ncm_order_id=ncm_order_id,
            tracking_id=tracking_id,
            vref_id=f"ORD-{locked_order.id}",
            origin_branch=service.default_origin_branch,
            destination_branch=valid_branch,
            delivery_type=delivery_type,
            package_description=package_description[:255],
            weight=Decimal(str(weight)),
            quoted_charge=quoted_charge,
            actual_charge=delivery_charge,
            cod_charge=cod_charge,
            courier_status='Order Created',
            status_history=[{
                'timestamp': timezone.now().isoformat(),
                'status': 'Order Created',
                'note': status_note,
            }],
            raw_response=api_res.get('raw_response', {}),
            last_synced_at=timezone.now(),
        )

        # Automatically initialize COD Remittance record if order has Cash on Delivery
        if locked_order.is_cod:
            CODRemittance.objects.get_or_create(
                order=locked_order,
                defaults={
                    'courier_shipment': shipment,
                    'expected_amount': locked_order.cod_remaining_balance,
                    'status': 'PENDING',
                }
            )

        locked_order.ncm_dispatch_status = 'CREATED'
        locked_order.ncm_dispatch_last_error = ''
        locked_order.ncm_dispatch_next_retry = None

        old_status = locked_order.status
        new_status = 'PROCESSING'
        if old_status != new_status:
            locked_order.status = new_status
            locked_order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry', 'status', 'updated_at'])

            OrderStatusHistory.objects.create(
                order=locked_order,
                previous_status=old_status,
                new_status=new_status,
                changed_by=admin_user,
                note=f"{status_note} (NCM Order ID: {ncm_order_id}, Branch: {valid_branch})",
            )
            locked_order.items.exclude(fulfillment_status='PROCESSING').update(fulfillment_status='PROCESSING')
        else:
            locked_order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry', 'updated_at'])

        _sync_dispatch_job(target_pk, status='COMPLETED')

    # Send student notification
    from core.notification_service import NotificationService
    NotificationService._create_if_allowed(
        recipient=locked_order.student,
        notif_type='marketplace',
        preference_key='marketplace_order_status_inapp',
        title='Order Dispatched via Courier',
        message=f"Your order #{locked_order.id} has been dispatched via Nepal Can Move (Tracking ID: {ncm_order_id}).",
        action_url=f"/student/marketplace/orders/{locked_order.id}",
    )

    logger.info("Successfully created NCM shipment #%s for Order #%s", ncm_order_id, locked_order.id)
    return {
        "status": "CREATED",
        "ncm_order_id": ncm_order_id,
        "tracking_id": tracking_id,
        "destination_branch": valid_branch,
        "cod_charge": str(cod_charge),
    }


def trigger_ncm_auto_dispatch(order_id: int) -> None:
    """
    Safely triggers automatic NCM courier dispatch in the background.
    Strictly executed via transaction.on_commit() AFTER admin payment approval commits.

    Execution Strategy:
    1. Persists a durable database outbox record (NCMDispatchJob) for auditability & crash recovery.
    2. If Celery is configured and running in eager mode (e.g. test runner), executes synchronously.
    3. If Celery is in asynchronous mode, enqueues via Celery task.
    4. Starts a background daemon thread as an immediate local worker fallback so dispatch
       executes reliably even if no external Celery worker process is provisioned on Render.
    """
    # 1. Create or ensure durable outbox record exists
    try:
        from marketplace.models import NCMDispatchJob
        NCMDispatchJob.objects.get_or_create(
            order_id=order_id,
            status__in=['QUEUED', 'PROCESSING'],
            defaults={'status': 'QUEUED'}
        )
    except Exception as exc:
        logger.debug("NCMDispatchJob outbox persistence skipped: %s", exc)

    # 2. Celery enqueue (in eager mode executes immediately)
    is_eager = getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False)
    try:
        from marketplace.tasks import dispatch_order_courier_shipment_task
        dispatch_order_courier_shipment_task.delay(order_id)
        logger.info("Enqueued Celery task for NCM courier dispatch for Order #%s (eager=%s)", order_id, is_eager)
    except Exception as exc:
        logger.warning(
            "Celery task dispatch unavailable for Order #%s (%s). Falling back to background daemon thread.",
            order_id, exc
        )

    # 3. If not eager mode, spawn background daemon thread to guarantee immediate dispatch
    # on single-service deployments (e.g. Render Web Service without separate Celery worker)
    if not is_eager:
        try:
            thread = threading.Thread(
                target=execute_ncm_dispatch,
                args=(order_id,),
                daemon=True,
                name=f"NCMAutoDispatch-Order-{order_id}",
            )
            thread.start()
        except Exception as th_err:
            logger.warning("Could not launch background dispatch thread for Order #%s: %s", order_id, th_err)


def process_ncm_dispatch_queue(limit: int = 50) -> Dict[str, Any]:
    """
    Durable queue worker to drain and process queued or pending-retry NCM dispatches.
    Uses select_for_update(skip_locked=True) to prevent race conditions across web/worker processes.
    Enables automatic recovery from server restarts, network drops, or worker recycles.
    """
    from django.db.models import Q
    now = timezone.now()
    processed = 0
    succeeded = 0
    failed = 0

    order_ids_to_process = []
    try:
        with transaction.atomic():
            queued_orders = list(
                Order.objects.filter(
                    courier_shipment__isnull=True,
                ).filter(
                    Q(ncm_dispatch_status='QUEUED') |
                    Q(ncm_dispatch_status='FAILED', ncm_dispatch_next_retry__lte=now)
                ).select_for_update(skip_locked=True)[:limit]
            )
            for ord_obj in queued_orders:
                order_ids_to_process.append(ord_obj.id)

            from .models import NCMDispatchJob
            remaining = limit - len(order_ids_to_process)
            if remaining > 0:
                queued_jobs = list(
                    NCMDispatchJob.objects.filter(
                        status='QUEUED',
                        order__courier_shipment__isnull=True,
                    ).exclude(
                        order_id__in=order_ids_to_process
                    ).select_for_update(skip_locked=True)[:remaining]
                )
                for j in queued_jobs:
                    order_ids_to_process.append(j.order_id)
    except Exception as exc:
        logger.warning("Could not lock queued orders for dispatch queue processing: %s", exc)
        return {"processed": 0, "succeeded": 0, "failed": 0, "error": str(exc)}

    for oid in order_ids_to_process:
        try:
            res = execute_ncm_dispatch(oid)
            processed += 1
            if res.get("status") in ("CREATED", "ALREADY_DISPATCHED"):
                succeeded += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error("Error executing queued NCM dispatch for Order #%s: %s", oid, exc)
            failed += 1

    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
    }

