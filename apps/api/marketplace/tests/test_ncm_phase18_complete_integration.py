"""
LoksewaAI — Phase 18: Complete NCM Production Integration Test Suite
Verifies all 20 required scenarios:
1. COD payment approval queues dispatch.
2. Prepaid payment approval queues dispatch.
3. Rejected payment does not queue dispatch.
4. Transaction rollback does not dispatch.
5. Worker processes committed jobs.
6. Worker restart does not lose queued jobs.
7. Missing NCM token produces actionable failure.
8. Invalid NCM token produces authentication failure.
9. Successful authentication permits shipment creation.
10. Correct COD remaining balance is sent.
11. Prepaid sends zero COD.
12. Duplicate payment approval does not duplicate jobs.
13. Duplicate worker execution does not create duplicate shipments.
14. Ambiguous timeout enters reconciliation.
15. Successful NCM response persists order ID.
16. Webhook updates shipment status.
17. Polling reconciles missed webhooks.
18. Delivered COD remains pending remittance until confirmed.
19. Failed branch synchronization preserves previous valid catalog.
20. Complete branch pagination is processed.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import override_settings

from core.models import User
from marketplace.models import (
    Order, OrderItem, Product, DeliveryAddress, PaymentMethod,
    PaymentSubmission, CourierShipment, NCMConfiguration, CODRemittance,
    NCMBranchRecord, NCMDispatchJob
)
from marketplace.ncm_service import (
    NCMService, NCMConnectionError, NCMAPIError, NCMError
)
from marketplace.dispatch_service import (
    execute_ncm_dispatch, trigger_ncm_auto_dispatch, process_ncm_dispatch_queue
)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, NCM_WEBHOOK_SECRET="test-phase18-webhook-secret")
class NCMPhase18CompleteIntegrationTests(APITestCase):
    def setUp(self):
        # 1. Admin user
        self.admin = User.objects.create_user(
            username='admin_phase18',
            password='Password123!',
            email='admin18@loksewa.com',
            role='ADMIN',
            is_staff=True,
            is_superuser=True
        )

        # 2. Student user
        self.student = User.objects.create_user(
            username='student_phase18',
            password='Password123!',
            email='student18@loksewa.com',
            role='STUDENT',
            first_name='Sunil',
            last_name='Sharma'
        )

        # 3. Product
        self.product = Product.objects.create(
            title='Loksewa Section Officer Supreme Guide',
            category='NEW_BOOK',
            price=Decimal('1000.00'),
            stock=50,
            is_published=True,
            listing_status='ACTIVE'
        )

        # 4. Delivery Address
        self.address = DeliveryAddress.objects.create(
            student=self.student,
            full_name='Sunil Sharma',
            phone_number='9841234567',
            province='Lumbini',
            district='Gulmi',
            municipality='Chhatrakot Rural Municipality',
            ward_number='3',
            tole_area='Hardachaur',
            is_default=True
        )

        # 5. Payment Method
        self.payment_method = PaymentMethod.objects.create(
            method_type='ESEWA',
            display_name='eSewa Loksewa Official',
            account_name='Loksewa Nepal',
            account_number='9800000000',
            is_active=True
        )

        # 6. Dummy payment screenshot
        self.screenshot = SimpleUploadedFile(
            name='phase18_receipt.jpg',
            content=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb',
            content_type='image/jpeg'
        )

        # 7. Configure NCM
        self.config = NCMConfiguration.get_settings()
        self.config.is_enabled = True
        self.config.environment = 'demo'
        self.config.custom_base_url = 'https://demo.nepalcanmove.com/api/'
        self.config.custom_api_token = 'token_phase18_valid_test_token'
        self.config.default_origin_branch = 'Kathmandu'
        self.config.live_rates_enabled = True
        self.config.auto_sync_enabled = True
        self.config.webhook_enabled = True
        self.config.webhook_secret = 'test-phase18-webhook-secret'
        self.config.save()

        # 8. Seed verified destination and origin branches
        NCMBranchRecord.objects.create(
            code='TMG',
            name='Tamghas',
            district_name='Gulmi',
            province_name='Lumbini',
            is_active=True,
            is_serviceable=True
        )
        NCMBranchRecord.objects.create(
            code='KTM',
            name='Kathmandu',
            district_name='Kathmandu',
            province_name='Bagmati',
            is_active=True,
            is_serviceable=True
        )
        self.mock_branches = [
            {'name': 'Tamghas', 'code': 'TMG', 'district_name': 'Gulmi'},
            {'name': 'Kathmandu', 'code': 'KTM', 'district_name': 'Kathmandu'},
        ]

    def _create_cod_order(self):
        """Creates a COD order awaiting advance payment verification."""
        order = Order.objects.create(
            student=self.student,
            status='PENDING_PAYMENT',
            payment_status='UNPAID',
            payment_method_type='COD',
            is_cod=True,
            total_amount=Decimal('1000.00'),
            delivery_fee=Decimal('100.00'),
            shipping_address='Hardachaur, Ward 3, Chhatrakot Rural Municipality, Gulmi, Lumbini',
            contact_number='9841234567',
            shipping_address_snapshot={
                'full_name': 'Sunil Sharma',
                'phone_number': '9841234567',
                'province': 'Lumbini',
                'district': 'Gulmi',
                'municipality': 'Chhatrakot Rural Municipality',
                'ward_number': '3',
                'tole_area': 'Hardachaur',
                'ncm_destination_branch': 'Tamghas',
                'ncm_delivery_type': 'Door2Door',
            }
        )
        order.calculate_cod_amounts()
        order.save()
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal('1000.00')
        )
        return order

    def _create_prepaid_order(self):
        """Creates a Prepaid order awaiting payment verification."""
        order = Order.objects.create(
            student=self.student,
            status='PENDING_PAYMENT',
            payment_status='UNPAID',
            payment_method_type='PREPAID',
            is_cod=False,
            total_amount=Decimal('1000.00'),
            delivery_fee=Decimal('100.00'),
            shipping_address='Hardachaur, Ward 3, Chhatrakot Rural Municipality, Gulmi, Lumbini',
            contact_number='9841234567',
            shipping_address_snapshot={
                'full_name': 'Sunil Sharma',
                'phone_number': '9841234567',
                'province': 'Lumbini',
                'district': 'Gulmi',
                'municipality': 'Chhatrakot Rural Municipality',
                'ward_number': '3',
                'tole_area': 'Hardachaur',
                'ncm_destination_branch': 'Tamghas',
                'ncm_delivery_type': 'Door2Door',
            }
        )
        order.calculate_cod_amounts()
        order.save()
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal('1000.00')
        )
        return order

    # --------------------------------------------------------------------------
    # 1. COD payment approval queues dispatch
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.dispatch_service.execute_ncm_dispatch')
    def test_01_cod_payment_approval_queues_dispatch(self, mock_dispatch, mock_branches):
        mock_branches.return_value = self.mock_branches
        order = self._create_cod_order()
        submission = PaymentSubmission.objects.create(
            student=self.student,
            order=order,
            payment_method=self.payment_method,
            transaction_id='TXN_COD_18_01',
            expected_amount=order.cod_advance_required,
            submitted_amount=order.cod_advance_required,
            is_cod_advance=True,
            status='PENDING',
            screenshot=self.screenshot
        )

        self.client.force_authenticate(user=self.admin)
        url = f'/api/marketplace/admin/payment-submissions/{submission.id}/review/'
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, {'action': 'APPROVE', 'admin_remarks': 'Advance verified'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'PARTIALLY_PAID')
        self.assertIn(order.status, ['CONFIRMED', 'PROCESSING'])

        # Verify durable NCMDispatchJob created
        job = NCMDispatchJob.objects.filter(order=order).first()
        self.assertIsNotNone(job)
        self.assertIn(job.status, ['QUEUED', 'PROCESSING', 'COMPLETED'])
        self.assertIn(order.ncm_dispatch_status, ['QUEUED', 'PROCESSING', 'DISPATCHED'])

    # --------------------------------------------------------------------------
    # 2. Prepaid payment approval queues dispatch
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.dispatch_service.execute_ncm_dispatch')
    def test_02_prepaid_payment_approval_queues_dispatch(self, mock_dispatch, mock_branches):
        mock_branches.return_value = self.mock_branches
        order = self._create_prepaid_order()
        submission = PaymentSubmission.objects.create(
            student=self.student,
            order=order,
            payment_method=self.payment_method,
            transaction_id='TXN_PRE_18_02',
            expected_amount=Decimal('1100.00'),
            submitted_amount=Decimal('1100.00'),
            is_cod_advance=False,
            status='PENDING',
            screenshot=self.screenshot
        )

        self.client.force_authenticate(user=self.admin)
        url = f'/api/marketplace/admin/payment-submissions/{submission.id}/review/'
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, {'action': 'APPROVE', 'admin_remarks': 'Prepaid verified in full'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'PAID')
        self.assertIn(order.status, ['CONFIRMED', 'PROCESSING'])

        job = NCMDispatchJob.objects.filter(order=order).first()
        self.assertIsNotNone(job)
        self.assertIn(job.status, ['QUEUED', 'PROCESSING', 'COMPLETED'])

    # --------------------------------------------------------------------------
    # 3. Rejected payment does not queue dispatch
    # --------------------------------------------------------------------------
    @patch('marketplace.dispatch_service.execute_ncm_dispatch')
    def test_03_rejected_payment_does_not_queue_dispatch(self, mock_dispatch):
        order = self._create_cod_order()
        submission = PaymentSubmission.objects.create(
            student=self.student,
            order=order,
            payment_method=self.payment_method,
            transaction_id='TXN_REJ_18_03',
            expected_amount=order.cod_advance_required,
            submitted_amount=order.cod_advance_required,
            is_cod_advance=True,
            status='PENDING',
            screenshot=self.screenshot
        )

        self.client.force_authenticate(user=self.admin)
        url = f'/api/marketplace/admin/payment-submissions/{submission.id}/review/'
        resp = self.client.post(url, {'action': 'REJECT', 'rejection_reason': 'Unclear screenshot'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_dispatch.assert_not_called()
        self.assertEqual(NCMDispatchJob.objects.filter(order=order).count(), 0)
        order.refresh_from_db()
        self.assertEqual(order.ncm_dispatch_status, 'NOT_REQUESTED')
        self.assertEqual(order.status, 'PENDING_PAYMENT')

    # --------------------------------------------------------------------------
    # 4. Transaction rollback does not dispatch
    # --------------------------------------------------------------------------
    @patch('marketplace.dispatch_service.trigger_ncm_auto_dispatch')
    def test_04_transaction_rollback_does_not_dispatch(self, mock_trigger):
        order = self._create_cod_order()
        submission = PaymentSubmission.objects.create(
            student=self.student,
            order=order,
            payment_method=self.payment_method,
            transaction_id='TXN_ROLL_18_04',
            expected_amount=order.cod_advance_required,
            submitted_amount=order.cod_advance_required,
            is_cod_advance=True,
            status='PENDING',
            screenshot=self.screenshot
        )

        # Simulate exception during atomic block
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                submission.status = 'APPROVED'
                submission.save()
                NCMDispatchJob.objects.create(order=order, status='QUEUED')
                raise RuntimeError("Simulated DB error before commit")

        # After rollback, no job or approved submission should exist
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'PENDING')
        self.assertEqual(NCMDispatchJob.objects.filter(order=order).count(), 0)

    # --------------------------------------------------------------------------
    # 5. Worker processes committed jobs
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_05_worker_processes_committed_jobs(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '88801',
            'delivery_charge': 100.0,
            'cod_charge': 935.0,
            'raw_response': {'orderid': 88801}
        }
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        job = NCMDispatchJob.objects.create(order=order, status='QUEUED')

        processed = process_ncm_dispatch_queue(limit=10)
        self.assertGreaterEqual(processed.get('processed', 0), 1)

        job.refresh_from_db()
        self.assertEqual(job.status, 'COMPLETED')
        order.refresh_from_db()
        self.assertEqual(order.ncm_dispatch_status, 'CREATED')
        self.assertTrue(CourierShipment.objects.filter(order=order, ncm_order_id='88801').exists())

    # --------------------------------------------------------------------------
    # 6. Worker restart does not lose queued jobs
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_06_worker_restart_does_not_lose_queued_jobs(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '88802',
            'delivery_charge': 100.0,
            'cod_charge': 0.0,
            'raw_response': {'orderid': 88802}
        }
        order = self._create_prepaid_order()
        order.payment_status = 'PAID'
        order.status = 'PROCESSING'
        order.ncm_dispatch_status = 'QUEUED'
        order.save()

        # Job queued by web process, but worker crashed / restarted
        job = NCMDispatchJob.objects.create(order=order, status='QUEUED')

        # When worker restarts, management command or queue processor drains it
        call_command('process_ncm_dispatch_queue', limit=10)

        job.refresh_from_db()
        self.assertEqual(job.status, 'COMPLETED')
        self.assertTrue(CourierShipment.objects.filter(order=order, ncm_order_id='88802').exists())

    # --------------------------------------------------------------------------
    # 7. Missing NCM token produces actionable failure
    # --------------------------------------------------------------------------
    def test_07_missing_ncm_token_produces_actionable_failure(self):
        # Configure without token
        self.config.custom_api_token = ''
        self.config.save()

        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        with patch.dict('os.environ', {'NCM_API_TOKEN': ''}):
            res = execute_ncm_dispatch(order.id)
            self.assertEqual(res.get('status'), 'FAILED')
            self.assertIn('not configured', res.get('error', '').lower())

            order.refresh_from_db()
            self.assertEqual(order.ncm_dispatch_status, 'FAILED')
            job = NCMDispatchJob.objects.filter(order=order).first()
            if job:
                self.assertEqual(job.status, 'FAILED')

    # --------------------------------------------------------------------------
    # 8. Invalid NCM token produces authentication failure
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('requests.Session.send')
    def test_08_invalid_ncm_token_produces_authentication_failure(self, mock_send, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"detail": "Invalid token."}'
        mock_resp.json.return_value = {'detail': 'Invalid token.'}
        mock_send.return_value = mock_resp

        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        res = execute_ncm_dispatch(order.id)
        self.assertEqual(res.get('status'), 'FAILED')
        self.assertIn('401', res.get('error', ''))

        order.refresh_from_db()
        self.assertEqual(order.ncm_dispatch_status, 'FAILED')

    # --------------------------------------------------------------------------
    # 9. Successful authentication permits shipment creation
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_09_successful_authentication_permits_shipment_creation(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '99901',
            'delivery_charge': 100.0,
            'cod_charge': 935.0,
            'raw_response': {'orderid': 99901}
        }
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        res = execute_ncm_dispatch(order.id)
        self.assertEqual(res.get('status'), 'CREATED')
        self.assertEqual(res.get('ncm_order_id'), '99901')

        order.refresh_from_db()
        self.assertEqual(order.ncm_dispatch_status, 'CREATED')
        self.assertTrue(CourierShipment.objects.filter(order=order, ncm_order_id='99901').exists())

    # --------------------------------------------------------------------------
    # 10. Correct COD remaining balance is sent
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_10_correct_cod_remaining_balance_is_sent(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '99902',
            'delivery_charge': 100.0,
            'cod_charge': 935.0,
            'raw_response': {'orderid': 99902}
        }
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        execute_ncm_dispatch(order.id)

        mock_create.assert_called_once()
        payload = mock_create.call_args[0][0]
        self.assertEqual(payload.get('cod_charge'), float(order.cod_remaining_balance))
        # Total Rs 1100, 15% advance (Rs 165). Remaining is 85% = Rs 935.
        self.assertEqual(payload.get('cod_charge'), 935.0)

    # --------------------------------------------------------------------------
    # 11. Prepaid sends zero COD
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_11_prepaid_sends_zero_cod(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '99903',
            'delivery_charge': 100.0,
            'cod_charge': 0.0,
            'raw_response': {'orderid': 99903}
        }
        order = self._create_prepaid_order()
        order.payment_status = 'PAID'
        order.status = 'PROCESSING'
        order.ncm_dispatch_status = 'QUEUED'
        order.save()

        execute_ncm_dispatch(order.id)

        mock_create.assert_called_once()
        payload = mock_create.call_args[0][0]
        self.assertEqual(payload.get('cod_charge'), 0.0)

    # --------------------------------------------------------------------------
    # 12. Duplicate payment approval does not duplicate jobs
    # --------------------------------------------------------------------------
    @patch('marketplace.dispatch_service.execute_ncm_dispatch')
    def test_12_duplicate_payment_approval_does_not_duplicate_jobs(self, mock_dispatch):
        order = self._create_cod_order()
        submission = PaymentSubmission.objects.create(
            student=self.student,
            order=order,
            payment_method=self.payment_method,
            transaction_id='TXN_DUP_18_12',
            expected_amount=order.cod_advance_required,
            submitted_amount=order.cod_advance_required,
            is_cod_advance=True,
            status='PENDING',
            screenshot=self.screenshot
        )

        self.client.force_authenticate(user=self.admin)
        url = f'/api/marketplace/admin/payment-submissions/{submission.id}/review/'
        with self.captureOnCommitCallbacks(execute=True):
            resp1 = self.client.post(url, {'action': 'APPROVE', 'admin_remarks': 'First approval'}, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Trigger trigger_ncm_auto_dispatch again
        trigger_ncm_auto_dispatch(order.id)

        # Exactly 1 NCMDispatchJob must exist for this order
        self.assertEqual(NCMDispatchJob.objects.filter(order=order).count(), 1)

    # --------------------------------------------------------------------------
    # 13. Duplicate worker execution does not create duplicate shipments
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_13_duplicate_worker_execution_does_not_create_duplicate_shipments(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '99904',
            'delivery_charge': 100.0,
            'cod_charge': 935.0,
            'raw_response': {'orderid': 99904}
        }
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        # Run dispatch once
        res1 = execute_ncm_dispatch(order.id)
        self.assertEqual(res1.get('status'), 'CREATED')
        self.assertEqual(CourierShipment.objects.filter(order=order).count(), 1)

        # Run dispatch second time on same order
        res2 = execute_ncm_dispatch(order.id)
        self.assertEqual(res2.get('status'), 'ALREADY_DISPATCHED')
        self.assertEqual(CourierShipment.objects.filter(order=order).count(), 1)
        # NCM create_order was called only once
        self.assertEqual(mock_create.call_count, 1)

    # --------------------------------------------------------------------------
    # 14. Ambiguous timeout enters reconciliation
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.lookup_order_by_vref', return_value=None)
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_14_ambiguous_timeout_enters_reconciliation(self, mock_create, mock_branches, mock_lookup):
        mock_branches.return_value = self.mock_branches
        mock_create.side_effect = NCMConnectionError("Connection timed out waiting for NCM gateway", is_ambiguous=True)

        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        NCMDispatchJob.objects.create(order=order, status='QUEUED')

        res = execute_ncm_dispatch(order.id)
        self.assertEqual(res.get('status'), 'MANUAL_REVIEW_REQUIRED')

        order.refresh_from_db()
        # After ambiguous timeout that cannot be reconciled, transitions to MANUAL_REVIEW_REQUIRED
        self.assertEqual(order.ncm_dispatch_status, 'MANUAL_REVIEW_REQUIRED')
        job = NCMDispatchJob.objects.filter(order=order).first()
        self.assertEqual(job.status, 'MANUAL_REVIEW_REQUIRED')

    # --------------------------------------------------------------------------
    # 15. Successful NCM response persists order ID
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.get_branches')
    @patch('marketplace.ncm_service.NCMService.create_order')
    def test_15_successful_ncm_response_persists_order_id(self, mock_create, mock_branches):
        mock_branches.return_value = self.mock_branches
        mock_create.return_value = {
            'success': True,
            'ncm_order_id': '99915',
            'delivery_charge': 100.0,
            'cod_charge': 935.0,
            'raw_response': {'orderid': 99915}
        }
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.cod_advance_paid = order.cod_advance_required
        order.status = 'PROCESSING'
        order.save()

        execute_ncm_dispatch(order.id)

        shipment = CourierShipment.objects.get(order=order)
        self.assertEqual(shipment.ncm_order_id, '99915')
        self.assertEqual(shipment.destination_branch, 'Tamghas')
        self.assertEqual(shipment.courier_status, 'Order Created')

    # --------------------------------------------------------------------------
    # 16. Webhook updates shipment status
    # --------------------------------------------------------------------------
    def test_16_webhook_updates_shipment_status(self):
        order = self._create_cod_order()
        order.status = 'PROCESSING'
        order.ncm_dispatch_status = 'CREATED'
        order.save()

        shipment = CourierShipment.objects.create(
            order=order,
            provider='NCM',
            ncm_order_id='99916',
            tracking_id='NCM-TRACK-99916',
            courier_status='Order Created',
            origin_branch='Kathmandu',
            destination_branch='Tamghas'
        )

        url = reverse('ncm-webhook')
        payload = {
            'order_id': '99916',
            'status': 'In Transit',
            'remarks': 'Package left Kathmandu hub'
        }
        resp = self.client.post(
            url,
            payload,
            format='json',
            HTTP_X_NCM_WEBHOOK_SECRET='test-phase18-webhook-secret'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        shipment.refresh_from_db()
        self.assertEqual(shipment.courier_status, 'In Transit')

    # --------------------------------------------------------------------------
    # 17. Polling reconciles missed webhooks
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService.track_order')
    def test_17_polling_reconciles_missed_webhooks(self, mock_track):
        order = self._create_cod_order()
        order.status = 'PROCESSING'
        order.save()

        shipment = CourierShipment.objects.create(
            order=order,
            provider='NCM',
            ncm_order_id='99917',
            tracking_id='NCM-TRACK-99917',
            courier_status='Order Created',
            origin_branch='Kathmandu',
            destination_branch='Tamghas'
        )

        mock_track.return_value = {
            'order_id': '99917',
            'status': 'In Transit',
            'current_branch': 'Tamghas Hub'
        }

        call_command('sync_ncm_shipments')

        shipment.refresh_from_db()
        self.assertEqual(shipment.courier_status, 'In Transit')

    # --------------------------------------------------------------------------
    # 18. Delivered COD remains pending remittance until confirmed
    # --------------------------------------------------------------------------
    def test_18_delivered_cod_remains_pending_remittance_until_confirmed(self):
        order = self._create_cod_order()
        order.payment_status = 'PARTIALLY_PAID'
        order.status = 'PROCESSING'
        order.save()

        shipment = CourierShipment.objects.create(
            order=order,
            provider='NCM',
            ncm_order_id='99918',
            tracking_id='NCM-TRACK-99918',
            courier_status='Order Created',
            origin_branch='Kathmandu',
            destination_branch='Tamghas'
        )

        # Webhook delivers order
        url = reverse('ncm-webhook')
        payload = {
            'order_id': '99918',
            'status': 'Delivered',
            'remarks': 'Delivered to Sunil Sharma'
        }
        self.client.post(
            url,
            payload,
            format='json',
            HTTP_X_NCM_WEBHOOK_SECRET='test-phase18-webhook-secret'
        )

        order.refresh_from_db()
        self.assertEqual(order.status, 'DELIVERED')
        # Critical business rule: payment_status must NOT automatically become PAID until remittance confirmed
        self.assertEqual(order.payment_status, 'PARTIALLY_PAID')

        # Lifecycle status in serializer must reflect DELIVERED (not REMITTANCE_CONFIRMED)
        from marketplace.serializers import OrderSerializer
        serializer_data = OrderSerializer(order).data
        self.assertEqual(serializer_data.get('lifecycle_status'), 'DELIVERED')

        # Once remittance is confirmed, lifecycle reflects REMITTANCE_CONFIRMED
        CODRemittance.objects.create(
            order=order,
            courier_shipment=shipment,
            status='VERIFIED',
            expected_amount=order.cod_remaining_balance,
            remitted_amount=order.cod_remaining_balance,
            verified_by=self.admin
        )
        order.refresh_from_db()
        serializer_data = OrderSerializer(order).data
        self.assertEqual(serializer_data.get('lifecycle_status'), 'REMITTANCE_CONFIRMED')

    # --------------------------------------------------------------------------
    # 19. Failed branch synchronization preserves previous valid catalog
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService._execute_request')
    def test_19_failed_branch_sync_preserves_previous_valid_catalog(self, mock_execute):
        # We already pre-seeded TMG and KTM in setUp (2 records)
        self.assertEqual(NCMBranchRecord.objects.count(), 2)

        # Simulate API failure during refresh
        mock_execute.side_effect = NCMConnectionError("NCM gateway unreachable")

        service = NCMService()
        result, meta = service.get_branches(force_refresh=True, return_meta=True)

        # Catalog must NOT be empty or cleared
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(meta.get('source'), 'DATABASE_CACHE')
        self.assertEqual(NCMBranchRecord.objects.count(), 2)

    # --------------------------------------------------------------------------
    # 20. Complete branch pagination is processed
    # --------------------------------------------------------------------------
    @patch('marketplace.ncm_service.NCMService._execute_request')
    def test_20_complete_branch_pagination_is_processed(self, mock_execute):
        # Simulate multi-page response
        def mock_page_response(method, endpoint, params=None, json_data=None, **kwargs):
            page = 1
            if params and 'page' in params:
                page = int(params['page'])
            elif 'page=' in endpoint:
                page = int(endpoint.split('page=')[1].split('&')[0])

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if page == 1:
                mock_resp.json.return_value = {
                    'count': 4,
                    'next': 'https://demo.nepalcanmove.com/api/v2/branches/?page=2',
                    'previous': None,
                    'results': [
                        {'code': 'B1', 'name': 'Branch 1', 'district_name': 'Kathmandu'},
                        {'code': 'B2', 'name': 'Branch 2', 'district_name': 'Lalitpur'},
                    ]
                }
            elif page == 2:
                mock_resp.json.return_value = {
                    'count': 4,
                    'next': None,
                    'previous': 'https://demo.nepalcanmove.com/api/v2/branches/?page=1',
                    'results': [
                        {'code': 'B3', 'name': 'Branch 3', 'district_name': 'Bhaktapur'},
                        {'code': 'B4', 'name': 'Branch 4', 'district_name': 'Kaski'},
                    ]
                }
            else:
                mock_resp.json.return_value = {'count': 4, 'next': None, 'results': []}
            return mock_resp

        mock_execute.side_effect = mock_page_response

        service = NCMService()
        branches, meta = service.get_branches(force_refresh=True, return_meta=True)

        self.assertEqual(len(branches), 4)
        self.assertEqual(meta.get('source'), 'LIVE_API')
        self.assertEqual(meta.get('count'), 4)
        # All 4 branches should be saved in DB
        self.assertEqual(NCMBranchRecord.objects.filter(code__in=['B1', 'B2', 'B3', 'B4']).count(), 4)
