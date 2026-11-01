import logging
from django.utils import timezone
from django.core.management.base import BaseCommand
from marketplace.models import CourierShipment, NCMConfiguration, CourierSyncLog
from marketplace.ncm_service import NCMService, NCMError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronizes active Nepal Can Move (NCM) courier shipments with provider tracking."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of shipments to synchronize in one execution (default: 50).'
        )
        parser.add_argument(
            '--order-id',
            type=int,
            default=None,
            help='Specific order ID to synchronize.'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force synchronization even if auto-sync is disabled in configuration.'
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        order_id = options.get('order_id')
        force = options.get('force')

        config = NCMConfiguration.get_settings()
        if not config.auto_sync_enabled and not force and not order_id:
            self.stdout.write(
                self.style.WARNING("NCM auto-synchronization is paused in admin configuration. Exiting (use --force to bypass).")
            )
            return

        qs = CourierShipment.objects.filter(provider='NCM').select_related('order')
        if order_id:
            qs = qs.filter(order_id=order_id)
        else:
            qs = qs.exclude(order__status__in=['DELIVERED', 'CANCELLED', 'REFUNDED']).order_by('last_synced_at')[:limit]

        shipments = list(qs)
        if not shipments:
            self.stdout.write(self.style.SUCCESS("No active NCM shipments to synchronize."))
            return

        self.stdout.write(f"Synchronizing {len(shipments)} active NCM courier shipment(s)...")

        ncm_service = NCMService()
        synced_count = 0
        transitioned_count = 0
        error_count = 0
        error_details = []

        for shipment in shipments:
            try:
                tracking_data = ncm_service.track_order(shipment.ncm_order_id)
                new_courier_status = None
                history_list = None
                tracking_id = None

                if isinstance(tracking_data, dict):
                    inner = tracking_data.get('data') or tracking_data
                    if isinstance(inner, dict):
                        new_courier_status = (
                            inner.get('status') or
                            inner.get('state') or
                            inner.get('courier_status')
                        )
                        tracking_id = (
                            inner.get('tracking_id') or
                            inner.get('trackingid')
                        )
                        history_list = inner.get('history') or inner.get('timeline')
                    elif isinstance(inner, list) and inner:
                        history_list = inner
                        new_courier_status = str(inner[-1].get('status') or shipment.courier_status)
                elif isinstance(tracking_data, list):
                    history_list = tracking_data
                    if tracking_data:
                        new_courier_status = str(tracking_data[-1].get('status') or shipment.courier_status)

                status_changed = shipment.apply_status_update(
                    new_courier_status=str(new_courier_status) if new_courier_status else None,
                    history_list=history_list,
                    tracking_id=str(tracking_id) if tracking_id else None,
                    source="sync_ncm_shipments_command"
                )

                synced_count += 1
                if status_changed:
                    transitioned_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Order #{shipment.order_id} (NCM #{shipment.ncm_order_id}) status transitioned to {shipment.order.status}"
                        )
                    )
                else:
                    self.stdout.write(
                        f"Order #{shipment.order_id} (NCM #{shipment.ncm_order_id}) status verified: {shipment.courier_status}"
                    )
            except NCMError as e:
                error_count += 1
                error_details.append({
                    'ncm_order_id': shipment.ncm_order_id,
                    'order_id': shipment.order_id,
                    'error': str(e),
                })
                self.stderr.write(
                    self.style.WARNING(f"Failed to track NCM shipment #{shipment.ncm_order_id} (Order #{shipment.order_id}): {e}")
                )
            except Exception as e:
                error_count += 1
                error_details.append({
                    'ncm_order_id': shipment.ncm_order_id,
                    'order_id': shipment.order_id,
                    'error': str(e),
                })
                logger.exception("Unexpected error syncing NCM shipment #%s", shipment.ncm_order_id)
                self.stderr.write(
                    self.style.ERROR(f"Unexpected error syncing shipment #{shipment.ncm_order_id}: {e}")
                )

        sync_status = 'SUCCESS'
        if error_count > 0:
            sync_status = 'PARTIAL' if synced_count > 0 else 'FAILED'

        CourierSyncLog.objects.create(
            trigger_type='cron',
            shipments_checked=len(shipments),
            shipments_updated=transitioned_count,
            errors_count=error_count,
            error_details=error_details[:20],
            status=sync_status,
        )

        config.last_sync_at = timezone.now()
        config.last_sync_status = sync_status
        config.save(update_fields=['last_sync_at', 'last_sync_status'])

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync completed: {synced_count} synced, {transitioned_count} transitioned, {error_count} failed."
            )
        )

        # Process any queued or pending retry dispatches
        from marketplace.dispatch_service import process_ncm_dispatch_queue
        dispatch_res = process_ncm_dispatch_queue(limit=25)
        if dispatch_res.get('processed', 0) > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {dispatch_res['processed']} queued/pending dispatches "
                    f"({dispatch_res['succeeded']} succeeded, {dispatch_res['failed']} failed)."
                )
            )

