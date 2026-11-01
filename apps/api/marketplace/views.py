import logging
import hmac
from core.validators import get_nepal_province_for_district
from rest_framework import viewsets, permissions, status

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from django.db.models import Sum, Q, Count
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from rest_framework.pagination import PageNumberPagination
from core.pagination import StandardResultsSetPagination
from .ncm_service import (
    NCMService, NCMError, NCMConfigurationError,
    NCMConnectionError, NCMAPIError, NCMValidationError,
    match_ncm_branches_for_location, normalize_location_name,
    discover_nearest_ncm_branches,
)

class MarketplacePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if 'page' in request.query_params or 'page_size' in request.query_params:
            return super().paginate_queryset(queryset, request, view)
        return None


from .models import (
    Product, PaymentMethod, PaymentSubmission, Purchase,
    Cart, CartItem, Order, OrderItem, DeliveryAddress, DeliveryFeeRule,
    OrderStatusHistory, MarketplaceSettings, MarketplaceListingReport,
    ProductImage, Review, Dispute, DisputeEvidence, CourierShipment,
    NCMConfiguration, NCMWebhookEvent, CourierSyncLog, CODRemittance,
    NCMBranchRecord, NCMBranchCoordinateAuditLog,
)
from .serializers import (
    ProductSerializer, SellerListingSerializer,
    PaymentMethodSerializer,
    PaymentSubmissionSerializer, PaymentSubmissionAdminReviewSerializer,
    PurchaseSerializer,
    CartSerializer, CartItemSerializer,
    OrderSerializer, CourierShipmentSerializer,
    DeliveryAddressSerializer, DeliveryFeeRuleSerializer,
    MarketplaceSettingsSerializer, MarketplacePricingPolicySerializer, MarketplaceListingReportSerializer,
    SellerSaleSerializer,
    ReviewSerializer, DisputeSerializer, DisputeEvidenceSerializer,
    NCMConfigurationSerializer, NCMWebhookEventSerializer, CourierSyncLogSerializer, CODRemittanceSerializer,
    NCMBranchRecordSerializer, NCMBranchCoordinateAuditLogSerializer,
)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and (
                getattr(request.user, 'role', None) in ['admin', 'super-admin']
                or getattr(request.user, 'is_staff', False)
                or getattr(request.user, 'is_superuser', False)
            )
        )


class IsAdminUserOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(
            request.user and request.user.is_authenticated
            and (
                getattr(request.user, 'role', None) in ['admin', 'super-admin']
                or getattr(request.user, 'is_staff', False)
                or getattr(request.user, 'is_superuser', False)
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _marketplace_enabled():
    from core.models import AdminSettings
    return AdminSettings.get_settings().enable_marketplace


def _validate_ncm_branch(branch_name_or_code, service):
    """Validate branch name or code against active NCM branches. Returns canonical branch name or None."""
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
    except Exception as e:
        logger.warning("Error validating NCM branch %s: %s", branch_name_or_code, e)
        return None


def _resolve_branch_from_address(address, service):
    """Match address district/municipality to an active NCM branch if possible."""
    if not address:
        return None
    dist = str(getattr(address, 'district', '') or '').strip().lower()
    mun = str(getattr(address, 'municipality', '') or '').strip().lower()
    if not dist and not mun:
        return None

    try:
        branches = service.get_branches()
        if mun:
            for b in branches:
                name = str(b.get('name') or '').strip().lower()
                if name == mun:
                    return str(b.get('name')).strip()
        if dist:
            for b in branches:
                name = str(b.get('name') or '').strip().lower()
                b_dist = str(b.get('district_name') or b.get('district') or '').strip().lower()
                if name == dist or b_dist == dist:
                    return str(b.get('name')).strip()
        return None
    except Exception as e:
        logger.warning("Error resolving NCM branch from address: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

class PublicProductListView(APIView):
    """GET /api/marketplace/public/products/ — anonymous-friendly preview for homepage."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get('limit', 24)), 100)
        except (TypeError, ValueError):
            limit = 24
        products = (
            Product.objects
            .filter(is_published=True, listing_status='ACTIVE')
            .select_related('target_exam', 'seller')
            .prefetch_related('images')
            .order_by('-created_at')[:limit]
        )

        def _cover(p, req):
            # Prefer primary ProductImage, fall back to cover_image field
            primary = next((img for img in p.images.all() if img.is_primary), None)
            if not primary and p.images.exists():
                primary = p.images.first()
            if primary and primary.image:
                try:
                    img_url = primary.image.url
                    if img_url:
                        if 'localhost' in img_url or '127.0.0.1' in img_url:
                            from urllib.parse import urlparse
                            parsed = urlparse(img_url)
                            img_url = parsed.path
                        return req.build_absolute_uri(img_url)
                except Exception:
                    pass
            if p.cover_image:
                try:
                    img_url = p.cover_image.url
                    if img_url:
                        if 'localhost' in img_url or '127.0.0.1' in img_url:
                            from urllib.parse import urlparse
                            parsed = urlparse(img_url)
                            img_url = parsed.path
                        return req.build_absolute_uri(img_url)
                except Exception:
                    pass
            return None

        data = [{
            'id': p.id,
            'title': p.title,
            'description': p.description,
            'category': p.category,
            'category_display': p.get_category_display(),
            'target_exam_name': p.target_exam.name if p.target_exam else None,
            'price': str(p.price),
            'discount_price': str(p.discount_price) if p.discount_price is not None else None,
            'final_price': str(p.final_price),
            'cover_image': _cover(p, request),
            'condition': p.condition,
            'condition_display': p.get_condition_display() if p.condition else None,
            'stock': p.stock,
            'listing_status': p.listing_status,
            'author': p.author,
            'publisher': p.publisher,
            'location': p.location,
            'is_seller_listing': p.is_seller_listing,
            'seller_details': {
                'id': p.seller.id,
                'first_name': p.seller.first_name,
                'member_since': p.seller.date_joined.strftime('%b %Y') if p.seller.date_joined else None,
            } if p.seller else None,
        } for p in products]
        return Response(data)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().select_related('seller').prefetch_related('images').order_by('-created_at')
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('listing_status')
        is_seller = self.request.query_params.get('is_seller_listing')
        if status_filter:
            qs = qs.filter(listing_status=status_filter)
        if is_seller == 'true':
            qs = qs.exclude(seller=None)
        elif is_seller == 'false':
            qs = qs.filter(seller=None)
        return qs

    def perform_create(self, serializer):
        is_published = serializer.validated_data.get('is_published', False)
        status_val = serializer.validated_data.get('listing_status')
        if not status_val:
            status_val = 'ACTIVE' if is_published else 'DRAFT'
        product = serializer.save(listing_status=status_val, is_published=is_published)
        self._handle_admin_images(product)

    def perform_update(self, serializer):
        is_published = serializer.validated_data.get('is_published', serializer.instance.is_published)
        status_val = serializer.validated_data.get('listing_status')
        if 'is_published' in serializer.validated_data and 'listing_status' not in serializer.validated_data:
            if is_published:
                status_val = 'ACTIVE'
            elif serializer.instance.listing_status == 'ACTIVE':
                status_val = 'DRAFT'
        if status_val:
            product = serializer.save(listing_status=status_val, is_published=is_published)
        else:
            product = serializer.save()
        self._handle_admin_images(product)

    def _handle_admin_images(self, product):
        """Process multiple uploaded images from admin request."""
        request = self.request
        uploaded = request.FILES.getlist('images')
        labels = request.POST.getlist('image_labels')
        primary_index = request.POST.get('primary_image_index')
        try:
            primary_index = int(primary_index) if primary_index is not None else None
        except (ValueError, TypeError):
            primary_index = None

        existing_count = product.images.count()
        if uploaded:
            for i, img_file in enumerate(uploaded):
                label = labels[i] if i < len(labels) else 'other'
                is_primary = False
                if primary_index is not None and i == primary_index:
                    is_primary = True
                elif existing_count == 0 and i == 0 and not product.cover_image:
                    is_primary = True

                if is_primary:
                    product.images.update(is_primary=False)

                pi = ProductImage.objects.create(
                    product=product,
                    image=img_file,
                    label=label,
                    is_primary=is_primary,
                )
                if is_primary:
                    product.cover_image = pi.image
                    product.save(update_fields=['cover_image'])

        delete_ids = request.data.getlist('delete_image_ids') if hasattr(request.data, 'getlist') else request.data.get('delete_image_ids', [])
        if delete_ids:
            if isinstance(delete_ids, (str, int)):
                delete_ids = [delete_ids]
            product.images.filter(id__in=delete_ids).delete()

    @action(detail=True, methods=['post'], url_path='delete-image')
    def delete_image(self, request, pk=None):
        """Admin deletes a specific ProductImage."""
        product = self.get_object()
        image_id = request.data.get('image_id')
        if not image_id:
            return Response({'detail': 'image_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        img = product.images.filter(pk=image_id).first()
        if not img:
            return Response({'detail': 'Image not found.'}, status=status.HTTP_404_NOT_FOUND)
        was_primary = img.is_primary
        img.delete()
        if was_primary:
            next_img = product.images.first()
            if next_img:
                next_img.is_primary = True
                next_img.save(update_fields=['is_primary'])
                product.cover_image = next_img.image
                product.save(update_fields=['cover_image'])
            else:
                product.cover_image = None
                product.save(update_fields=['cover_image'])
        return Response(ProductSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='set-primary-image')
    def set_primary_image(self, request, pk=None):
        """Admin sets a specific ProductImage as primary."""
        product = self.get_object()
        image_id = request.data.get('image_id')
        if not image_id:
            return Response({'detail': 'image_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        img = product.images.filter(pk=image_id).first()
        if not img:
            return Response({'detail': 'Image not found.'}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            product.images.update(is_primary=False)
            img.is_primary = True
            img.save(update_fields=['is_primary'])
            product.cover_image = img.image
            product.save(update_fields=['cover_image'])
        return Response(ProductSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='upload-images')
    def upload_images(self, request, pk=None):
        """Admin uploads multiple images to an existing product."""
        product = self.get_object()
        uploaded = request.FILES.getlist('images')
        if not uploaded:
            return Response({'detail': 'No images uploaded.'}, status=status.HTTP_400_BAD_REQUEST)
        labels = request.POST.getlist('image_labels')
        make_first_primary = request.data.get('set_first_as_primary') in [True, 'true', '1']
        for i, img_file in enumerate(uploaded):
            label = labels[i] if i < len(labels) else 'other'
            is_primary = False
            if (make_first_primary and i == 0) or (product.images.count() == 0 and not product.cover_image):
                product.images.update(is_primary=False)
                is_primary = True
            pi = ProductImage.objects.create(
                product=product,
                image=img_file,
                label=label,
                is_primary=is_primary,
            )
            if is_primary:
                product.cover_image = pi.image
                product.save(update_fields=['cover_image'])
        return Response(ProductSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Admin approves a PENDING_REVIEW student listing."""
        product = self.get_object()
        if product.listing_status not in ('PENDING_REVIEW', 'REJECTED'):
            return Response(
                {'detail': f'Cannot approve a listing in status {product.listing_status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            product.listing_status = 'ACTIVE'
            product.is_published = True
            product.rejection_reason = ''
            product.save(update_fields=['listing_status', 'is_published', 'rejection_reason', 'updated_at'])

        if product.seller:
            from core.notification_service import NotificationService
            NotificationService.notify_listing_approved(product.seller, product)

        return Response(ProductSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Admin rejects a student listing with an optional reason."""
        product = self.get_object()
        if product.listing_status not in ('PENDING_REVIEW', 'ACTIVE'):
            return Response(
                {'detail': f'Cannot reject a listing in status {product.listing_status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reason = request.data.get('reason', '').strip()
        with transaction.atomic():
            product.listing_status = 'REJECTED'
            product.is_published = False
            product.rejection_reason = reason
            product.save(update_fields=['listing_status', 'is_published', 'rejection_reason', 'updated_at'])

        if product.seller:
            from core.notification_service import NotificationService
            NotificationService.notify_listing_rejected(product.seller, product, reason)

        return Response(ProductSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Admin archives a listing."""
        product = self.get_object()
        with transaction.atomic():
            product.listing_status = 'ARCHIVED'
            product.is_published = False
            product.save(update_fields=['listing_status', 'is_published', 'updated_at'])
        return Response(ProductSerializer(product, context={'request': request}).data)


class AdminPaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAdminUser]


class AdminPaymentSubmissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentSubmission.objects.select_related(
        'student',
        'product',
        'product__seller',
        'payment_method',
        'order',
        'verified_by',
    ).order_by('-submitted_at')
    serializer_class = PaymentSubmissionSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    @action(detail=True, methods=['post'], serializer_class=PaymentSubmissionAdminReviewSerializer)
    def review(self, request, pk=None):
        with transaction.atomic():
            submission = PaymentSubmission.objects.select_for_update().filter(pk=pk).first()
            if not submission:
                return Response({"detail": "Payment submission not found."}, status=status.HTTP_404_NOT_FOUND)
            if submission.status != 'PENDING':
                return Response(
                    {"detail": "Submission is already processed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = PaymentSubmissionAdminReviewSerializer(submission, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            action_input = (request.data.get('action') or request.data.get('status') or '').upper().strip()
            if action_input in ['APPROVE', 'APPROVED']:
                new_status = 'APPROVED'
            elif action_input in ['REJECT', 'REJECTED']:
                new_status = 'REJECTED'
            else:
                new_status = serializer.validated_data.get('status')

            rejection_reason = (
                serializer.validated_data.get('rejection_reason') 
                or request.data.get('rejection_reason') 
                or request.data.get('reason') 
                or request.data.get('admin_notes') 
                or ''
            )

            if new_status == 'REJECTED' and not rejection_reason:
                return Response(
                    {"rejection_reason": ["Required when rejecting."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            submission.status = new_status
            submission.rejection_reason = rejection_reason if new_status == 'REJECTED' else ''
            submission.verified_at = timezone.now()
            submission.verified_by = request.user
            submission.save()

            if new_status == 'APPROVED':
                if submission.order:
                    old_order_status = submission.order.status
                    order = submission.order
                    final_tot = (order.total_amount + order.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    if submission.is_cod_advance or order.is_cod:
                        order.status = 'CONFIRMED'
                        order.payment_status = 'PARTIALLY_PAID'
                        order.cod_advance_paid = submission.submitted_amount
                        order.cod_remaining_balance = max(
                            Decimal('0.00'),
                            (final_tot - order.cod_advance_paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        )
                        order.ncm_dispatch_status = 'QUEUED'
                        order.ncm_dispatch_last_error = ''
                        order.save(update_fields=['status', 'payment_status', 'cod_advance_paid', 'cod_remaining_balance', 'ncm_dispatch_status', 'ncm_dispatch_last_error', 'updated_at'])
                        OrderStatusHistory.objects.create(
                            order=order,
                            previous_status=old_order_status,
                            new_status='CONFIRMED',
                            changed_by=request.user,
                            note=f'COD 15% advance payment (NPR {submission.submitted_amount}) verified by admin. Remaining balance NPR {order.cod_remaining_balance} payable on delivery.',
                        )
                    else:
                        order.status = 'CONFIRMED'
                        order.payment_status = 'PAID'
                        order.ncm_dispatch_status = 'QUEUED'
                        order.ncm_dispatch_last_error = ''
                        order.save(update_fields=['status', 'payment_status', 'ncm_dispatch_status', 'ncm_dispatch_last_error', 'updated_at'])
                        OrderStatusHistory.objects.create(
                            order=order,
                            previous_status=old_order_status,
                            new_status='CONFIRMED',
                            changed_by=request.user,
                            note='Full payment approved by admin',
                        )

                    # Create durable dispatch outbox record in same atomic transaction
                    try:
                        from marketplace.models import NCMDispatchJob
                        NCMDispatchJob.objects.get_or_create(
                            order=order,
                            status__in=['QUEUED', 'PROCESSING'],
                            defaults={'status': 'QUEUED'}
                        )
                    except Exception as _job_err:
                        logger.debug("NCMDispatchJob outbox persistence skipped: %s", _job_err)

                    # Trigger automatic NCM courier dispatch strictly post-commit!
                    from marketplace.dispatch_service import trigger_ncm_auto_dispatch
                    target_order_pk = order.pk
                    transaction.on_commit(lambda order_pk=target_order_pk: trigger_ncm_auto_dispatch(order_pk))
                elif submission.product:
                    Purchase.objects.update_or_create(
                        student=submission.student,
                        product=submission.product,
                        defaults={
                            'payment_submission': submission,
                            'amount_paid': submission.submitted_amount,
                            'status': 'ACTIVE',
                            'approved_at': timezone.now(),
                        }
                    )
            elif new_status == 'REJECTED':
                if submission.order:
                    old_order_status = submission.order.status
                    order = submission.order
                    order.status = 'PENDING_PAYMENT'
                    order.payment_status = 'UNPAID'
                    order.save(update_fields=['status', 'payment_status', 'updated_at'])
                    OrderStatusHistory.objects.create(
                        order=order,
                        previous_status=old_order_status,
                        new_status='PENDING_PAYMENT',
                        changed_by=request.user,
                        note=f'Payment attempt #{submission.attempt_number} rejected by admin: {rejection_reason}',
                    )

        from core.notification_service import NotificationService
        title = f"Order #{submission.order.id}" if submission.order else (
            submission.product.title if submission.product else "your item"
        )

        if new_status == 'APPROVED':
            NotificationService.notify_admins(
                notif_type='payment',
                title='Marketplace Order Approved',
                message=(
                    f"{request.user.get_full_name() or request.user.username} approved "
                    f"{submission.student.get_full_name() or submission.student.username}'s "
                    f"order for '{title}'."
                ),
                action_url='/admin-dashboard/marketplace/payments',
            )
            NotificationService.notify_student_payment_approved(
                student=submission.student,
                title_ref=title,
                action_url='/student/marketplace/orders' if submission.order else '/student/marketplace',
            )
            # Notify seller if S2S order
            if submission.order:
                seller_ids = set(
                    submission.order.items
                    .filter(product__seller__isnull=False)
                    .values_list('product__seller_id', flat=True)
                )
                from core.models import User as UserModel
                for seller in UserModel.objects.filter(id__in=seller_ids):
                    NotificationService.notify_seller_payment_confirmed(seller, submission.order.id)
            # Send admin order confirmation email (fires only after payment is verified)
            try:
                from core.email_notification_service import EmailNotificationService
                EmailNotificationService.send_admin_marketplace_order_email(submission.order)
            except Exception as _email_err:
                logger.warning('Failed to send admin marketplace order email: %s', _email_err)
        elif new_status == 'REJECTED':
            NotificationService.notify_admins(
                notif_type='payment',
                title='Marketplace Order Rejected',
                message=(
                    f"{request.user.get_full_name() or request.user.username} rejected "
                    f"{submission.student.get_full_name() or submission.student.username}'s "
                    f"order for '{title}'. Reason: {rejection_reason}"
                ),
                action_url='/admin-dashboard/marketplace/payments',
            )
            NotificationService.notify_student_payment_rejected(
                student=submission.student,
                title_ref=title,
                reason=rejection_reason,
                action_url='/student/marketplace/orders' if submission.order else '/student/marketplace',
            )

        return Response(PaymentSubmissionSerializer(submission).data)


class AdminPurchaseViewSet(viewsets.ReadOnlyModelViewSet):
    # Safe to paginate: adminGetPurchases() in lib/api/marketplace.ts is
    # defined but has no frontend caller today (grepped the whole apps/web
    # tree), so there's no array-typed consumer this would break.
    queryset = Purchase.objects.select_related(
        'student',
        'product',
        'product__seller',
        'payment_submission',
        'payment_submission__student',
        'payment_submission__payment_method',
    ).order_by('-created_at')
    serializer_class = PurchaseSerializer
    permission_classes = [IsAdminUser]
    pagination_class = StandardResultsSetPagination

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        purchase = self.get_object()
        if purchase.status == 'REVOKED':
            return Response({"detail": "Purchase is already revoked."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            purchase.status = 'REVOKED'
            purchase.save(update_fields=['status'])
        return Response(PurchaseSerializer(purchase).data)

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        purchase = self.get_object()
        if purchase.status == 'ACTIVE':
            return Response({"detail": "Purchase is already active."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            purchase.status = 'ACTIVE'
            purchase.save(update_fields=['status'])
        return Response(PurchaseSerializer(purchase).data)


class AdminOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Order.objects.all().select_related(
        'student',
        'delivery_address_ref',
        'courier_shipment',
    ).prefetch_related(
        'items__product',
        'items__product__seller',
        'items__product__images',
        'status_history',
        'status_history__changed_by',
        'payment_submissions',
        'payment_submissions__payment_method',
    ).order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status')
        note = request.data.get('note', '')

        valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({"detail": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        old_status = order.status
        if old_status == new_status:
            return Response({"detail": "Order is already in this status"}, status=status.HTTP_400_BAD_REQUEST)

        if old_status in ['DELIVERED', 'CANCELLED', 'REFUNDED'] and new_status not in ['CANCELLED', 'REFUNDED']:
            return Response(
                {"detail": f"Cannot transition from {old_status} to {new_status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from core.notification_service import NotificationService

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            order.status = new_status
            order.save()

            OrderStatusHistory.objects.create(
                order=order,
                previous_status=old_status,
                new_status=new_status,
                changed_by=request.user,
                note=note,
            )

            # Sync line-item fulfillment_status with order status
            if new_status in ['PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED']:
                order.items.exclude(fulfillment_status=new_status).update(fulfillment_status=new_status)

            # Mark order items ELIGIBLE for payout when order is DELIVERED
            if new_status == 'DELIVERED' and old_status != 'DELIVERED':
                order.items.filter(product__seller__isnull=False, payout_status='PENDING').update(payout_status='ELIGIBLE')

            # Return stock on cancellation (but not after delivery) and cancel pending payouts
            if new_status in ['CANCELLED', 'REFUNDED']:
                order.items.filter(payout_status__in=['PENDING', 'ON_HOLD', 'ELIGIBLE']).update(payout_status='CANCELLED')
                if old_status not in ['DELIVERED']:
                    for item in order.items.select_related('product').all():
                        p = Product.objects.select_for_update().get(pk=item.product_id)
                        p.stock += item.quantity
                        if p.stock > 0 and p.listing_status == 'SOLD':
                            p.listing_status = 'ACTIVE'
                            p.is_published = True
                        p.save(update_fields=['stock', 'listing_status', 'is_published'])

        # Buyer notification
        status_display = dict(Order.STATUS_CHOICES).get(new_status, new_status)
        NotificationService.notify_order_status(
            student=order.student,
            order_id=order.id,
            status_display=status_display,
            action_url='/student/marketplace/orders',
        )
        # Seller notifications for shipped/delivered
        if new_status == 'SHIPPED':
            seller_ids = set(
                order.items.filter(product__seller__isnull=False)
                .values_list('product__seller_id', flat=True)
            )
            from core.models import User as UserModel
            for seller in UserModel.objects.filter(id__in=seller_ids):
                NotificationService._create_if_allowed(
                    recipient=seller,
                    notif_type='system',
                    preference_key='system_alerts_inapp',
                    title='Your book has been shipped',
                    message=f"Order #{order.id} has been marked as shipped.",
                    action_url='/student/marketplace-listings',
                )

        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def update_item_status(self, request, pk=None):
        """Per-item companion to update_status above - the order-level status
        is the buyer-facing summary (PENDING_PAYMENT..DELIVERED), while this
        updates one line item's own fulfillment_status/payout_status
        (matters for multi-seller orders, where each seller's item ships and
        gets paid out independently of the others). Admin-only: the existing
        architecture gives sellers no self-service way to mark their own
        items shipped/delivered (SellerSalesViewSet is read-only) - payout
        eligibility is downstream of fulfillment_status, so only a trusted
        admin flips it, never the seller being paid."""
        order = self.get_object()
        item_id = request.data.get('item_id')
        try:
            item = order.items.get(id=item_id)
        except OrderItem.DoesNotExist:
            return Response({'detail': 'Item not found on this order.'}, status=status.HTTP_404_NOT_FOUND)

        fulfillment_status = request.data.get('fulfillment_status')
        payout_status = request.data.get('payout_status')
        valid_fulfillment = [c[0] for c in OrderItem.FULFILLMENT_CHOICES]
        valid_payout = [c[0] for c in OrderItem.PAYOUT_CHOICES]

        update_fields = []
        if fulfillment_status is not None:
            if fulfillment_status not in valid_fulfillment:
                return Response({'detail': 'Invalid fulfillment_status.'}, status=status.HTTP_400_BAD_REQUEST)
            item.fulfillment_status = fulfillment_status
            update_fields.append('fulfillment_status')
        if payout_status is not None:
            if payout_status not in valid_payout:
                return Response({'detail': 'Invalid payout_status.'}, status=status.HTTP_400_BAD_REQUEST)
            item.payout_status = payout_status
            update_fields.append('payout_status')

        if not update_fields:
            return Response({'detail': 'Provide fulfillment_status and/or payout_status.'}, status=status.HTTP_400_BAD_REQUEST)

        item.save(update_fields=update_fields)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='dispatch-ncm')
    def dispatch_ncm(self, request, pk=None):
        """
        Admin action to create a Nepal Can Move (NCM) courier shipment for an eligible order.
        Strict verification:
        1. Order must be CONFIRMED or PROCESSING.
        2. If COD: order.payment_status must be PARTIALLY_PAID (15% advance verified).
        3. If PREPAID: order.payment_status must be PAID (full payment verified).
        4. Idempotency: cannot dispatch if courier_shipment already exists.
        5. Validates destination branch and customer shipping details.
        6. Passes remaining 85% balance to NCM as cod_charge (0 for prepaid).
        """
        order = self.get_object()

        # 1. Status verification
        if order.status not in ['CONFIRMED', 'PROCESSING']:
            return Response(
                {"detail": f"Order #{order.id} is in status '{order.status}'. Only CONFIRMED or PROCESSING orders can be dispatched."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Payment verification
        if order.is_cod:
            if order.payment_status != 'PARTIALLY_PAID':
                return Response(
                    {"detail": f"Cannot dispatch COD order #{order.id} with payment status '{order.payment_status}'. The 15% advance payment must be verified first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            if order.payment_status != 'PAID':
                return Response(
                    {"detail": f"Cannot dispatch prepaid order #{order.id} with payment status '{order.payment_status}'. Full payment must be verified first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 3. Idempotency check: prevent duplicate shipment
        if hasattr(order, 'courier_shipment') and order.courier_shipment:
            return Response(
                {"detail": f"Shipment has already been created for Order #{order.id} (NCM Order ID: {order.courier_shipment.ncm_order_id}). Duplicate creation prevented."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Resolve delivery details from request or snapshot
        snapshot = order.shipping_address_snapshot or {}
        dest_branch = (request.data.get('destination_branch') or snapshot.get('ncm_destination_branch') or '').strip()
        if not dest_branch:
            return Response(
                {"detail": "Destination branch is required to create courier shipment."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = NCMService()
        if not service.is_configured():
            return Response(
                {"detail": "Nepal Can Move courier service is not configured (missing API token or base URL)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Validate destination branch against active branches
        valid_branch = _validate_ncm_branch(dest_branch, service)
        if not valid_branch:
            return Response(
                {"detail": f"'{dest_branch}' is not a recognized NCM branch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (request.data.get('name') or snapshot.get('full_name') or order.student.get_full_name() or order.student.username).strip()
        phone = (request.data.get('phone') or snapshot.get('phone_number') or order.contact_number).strip()
        phone2 = (request.data.get('phone2') or snapshot.get('phone2') or '').strip()
        instruction = (request.data.get('instruction') or snapshot.get('delivery_note') or '').strip()
        delivery_type = (request.data.get('delivery_type') or snapshot.get('ncm_delivery_type') or 'Door2Door').strip()

        # Build address string
        address = (
            request.data.get('address')
            or ", ".join(filter(None, [
                snapshot.get('tole_area'),
                f"Ward {snapshot.get('ward_number')}" if snapshot.get('ward_number') else "",
                snapshot.get('municipality'),
                snapshot.get('district'),
                snapshot.get('province'),
            ]))
            or order.shipping_address
        ).strip()

        if not name or not phone or not address:
            return Response(
                {"detail": "Customer name, phone number, and address are required for courier dispatch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Package description
        items = list(order.items.select_related('product').all())
        desc_parts = [f"{it.quantity}x {it.product.title}" for it in items[:3]]
        if len(items) > 3:
            desc_parts.append(f"+{len(items)-3} more items")
        package_description = request.data.get('package_description') or ", ".join(desc_parts)

        # Weight
        try:
            weight = float(request.data.get('weight') or '1.0')
            if weight <= 0:
                weight = 1.0
        except (ValueError, TypeError):
            weight = 1.0

        # COD Charge:
        # STRICT RULE: 15% advance was paid; NCM must collect remaining 85% balance.
        # For prepaid, NCM must collect 0.00.
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

        try:
            api_res = service.create_order(ncm_payload)
        except NCMConnectionError as exc:
            logger.error("NCM shipment creation failed with connection error: %s (ambiguous=%s)", exc, exc.is_ambiguous)
            return Response(
                {"detail": f"Failed to connect to NCM courier API: {str(exc)}. If this was a timeout, check the courier portal before retrying to prevent duplicate shipments."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except NCMError as exc:
            logger.error("NCM shipment creation API error: %s", exc)
            return Response(
                {"detail": f"NCM courier returned an error: {str(exc)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ncm_order_id = api_res["ncm_order_id"]
        delivery_charge = Decimal(str(api_res.get("delivery_charge", 0.0)))
        quoted_charge = Decimal(str(order.delivery_fee or "0.00"))

        with transaction.atomic():
            # Check duplicate again inside transaction with lock
            order = Order.objects.select_for_update().get(pk=order.pk)
            if hasattr(order, 'courier_shipment') and order.courier_shipment:
                return Response(
                    {"detail": f"Shipment already exists for order #{order.id}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            shipment = CourierShipment.objects.create(
                order=order,
                provider='NCM',
                ncm_order_id=ncm_order_id,
                tracking_id=ncm_order_id,
                vref_id=f"ORD-{order.id}",
                origin_branch=service.default_origin_branch,
                destination_branch=valid_branch,
                delivery_type=delivery_type,
                package_description=package_description[:255],
                weight=Decimal(str(weight)),
                quoted_charge=quoted_charge,
                actual_charge=delivery_charge,
                cod_charge=Decimal(str(cod_charge)),
                courier_status='Order Created',
                status_history=[{
                    'timestamp': timezone.now().isoformat(),
                    'status': 'Order Created',
                    'note': f'Created by admin {request.user.username}',
                }],
                raw_response=api_res.get('raw_response', {}),
                last_synced_at=timezone.now(),
            )

            # Automatically initialize COD Remittance record if order has Cash on Delivery
            if order.is_cod:
                CODRemittance.objects.get_or_create(
                    order=order,
                    defaults={
                        'courier_shipment': shipment,
                        'expected_amount': order.cod_remaining_balance,
                        'status': 'PENDING',
                    }
                )

            # Move order status to PROCESSING or SHIPPED
            order.ncm_dispatch_status = 'CREATED'
            order.ncm_dispatch_last_error = ''
            order.ncm_dispatch_next_retry = None
            old_status = order.status
            new_status = 'PROCESSING'
            if old_status != new_status:
                order.status = new_status
                order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry', 'status', 'updated_at'])

                OrderStatusHistory.objects.create(
                    order=order,
                    previous_status=old_status,
                    new_status=new_status,
                    changed_by=request.user,
                    note=f"Dispatched via NCM Courier (Shipment ID: {ncm_order_id}, Branch: {valid_branch})",
                )

                order.items.exclude(fulfillment_status='PROCESSING').update(fulfillment_status='PROCESSING')
            else:
                order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error', 'ncm_dispatch_next_retry', 'updated_at'])

        # Send notification to student
        from core.notification_service import NotificationService
        NotificationService._create_if_allowed(
            recipient=order.student,
            notif_type='marketplace',
            preference_key='marketplace_order_status_inapp',
            title='Order Dispatched via Courier',
            message=f"Your order #{order.id} has been dispatched via Nepal Can Move (Tracking ID: {ncm_order_id}).",
            action_url=f"/student/marketplace/orders/{order.id}",
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='retry-dispatch')
    def retry_dispatch(self, request, pk=None):
        """
        Admin action to retry failed or queued NCM courier dispatch.
        Guaranteed idempotent.
        """
        order = self.get_object()
        if hasattr(order, 'courier_shipment') and order.courier_shipment:
            return Response(
                {"detail": f"Shipment already exists for Order #{order.id} (NCM Order ID: {order.courier_shipment.ncm_order_id})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from marketplace.dispatch_service import execute_ncm_dispatch
        res = execute_ncm_dispatch(order.id, force_retry=True, admin_user=request.user)
        order.refresh_from_db()

        if res.get("status") in ["CREATED", "ALREADY_DISPATCHED"]:
            return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
        else:
            return Response(
                {
                    "detail": res.get("error") or "Failed to dispatch NCM shipment.",
                    "status": res.get("status"),
                    "order": OrderSerializer(order).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['post'], url_path='reconcile-dispatch')
    def reconcile_dispatch(self, request, pk=None):
        """
        Admin action to reconcile an order in MANUAL_REVIEW_REQUIRED or ambiguous timeout state.
        Queries NCM with vref_id (or optional admin supplied ncm_order_id).
        If confirmed, creates/links CourierShipment and transitions order to PROCESSING.
        """
        order = self.get_object()
        if hasattr(order, 'courier_shipment') and order.courier_shipment:
            return Response(
                {"detail": f"Shipment already exists for Order #{order.id} (NCM Order ID: {order.courier_shipment.ncm_order_id})."},
                status=status.HTTP_200_OK,
            )

        service = NCMService()
        if not service.is_configured():
            return Response({"detail": "NCM service not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        manual_ncm_id = request.data.get('ncm_order_id')
        reconciled = None

        if manual_ncm_id:
            try:
                details = service.get_order_details(str(manual_ncm_id).strip())
                inner = details.get('data') or details
                if inner and (inner.get('orderid') or inner.get('order_id') or inner.get('id')):
                    reconciled = inner
            except Exception as exc:
                return Response(
                    {"detail": f"Failed to verify NCM order ID '{manual_ncm_id}': {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            reconciled = service.lookup_order_by_vref(f"ORD-{order.id}")

        if reconciled and (reconciled.get("orderid") or reconciled.get("order_id") or reconciled.get("id")):
            from marketplace.dispatch_service import _persist_successful_ncm_shipment
            ncm_oid = str(reconciled.get("orderid") or reconciled.get("order_id") or reconciled.get("id"))
            snapshot = order.shipping_address_snapshot or {}
            valid_branch = (snapshot.get('ncm_destination_branch') or 'Kathmandu').strip()
            del_type = (snapshot.get('ncm_delivery_type') or 'Door2Door').strip()

            api_res = {
                "success": True,
                "ncm_order_id": ncm_oid,
                "tracking_id": str(reconciled.get("tracking_id") or ncm_oid),
                "delivery_charge": float(reconciled.get("delivery_charge", 0.0)),
                "cod_charge": float(reconciled.get("cod_charge", order.cod_remaining_balance if order.is_cod else 0.0)),
                "raw_response": reconciled,
            }
            _persist_successful_ncm_shipment(
                api_res=api_res,
                valid_branch=valid_branch,
                delivery_type=del_type,
                package_description="Loksewa Study Material",
                weight=1.0,
                service=service,
                order_id=order.id,
                admin_user=request.user,
                is_reconciled=True,
            )
            order.refresh_from_db()
            return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
        else:
            # Not found in NCM: admin can safely reset status to FAILED to allow re-dispatch
            reset = request.data.get('reset_to_failed', False)
            if reset:
                with transaction.atomic():
                    order = Order.objects.select_for_update().get(pk=order.pk)
                    order.ncm_dispatch_status = 'FAILED'
                    order.ncm_dispatch_last_error = f"Reconciled by admin {request.user.username}: No shipment found in NCM portal."
                    order.save(update_fields=['ncm_dispatch_status', 'ncm_dispatch_last_error'])
                return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

            return Response(
                {
                    "detail": f"No existing NCM shipment found for ORD-{order.id}. If you verified on the NCM portal that no shipment exists, submit with reset_to_failed=true to allow retrying.",
                    "reconciled": False,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Send notification to student
        from core.notification_service import NotificationService
        NotificationService._create_if_allowed(
            recipient=order.student,
            notif_type='marketplace',
            preference_key='marketplace_order_status_inapp',
            title='Order Dispatched via Courier',
            message=f"Your order #{order.id} has been dispatched via Nepal Can Move (Tracking ID: {ncm_order_id}).",
            action_url=f"/student/marketplace/orders/{order.id}",
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='sync-courier')
    def sync_courier(self, request, pk=None):
        """
        Synchronize courier tracking status from NCM for this order's shipment.
        Updates CourierShipment without bypassing payment rules.
        """
        order = self.get_object()
        if not hasattr(order, 'courier_shipment') or not order.courier_shipment:
            return Response(
                {"detail": "No courier shipment found for this order."},
                status=status.HTTP_404_NOT_FOUND,
            )

        shipment = order.courier_shipment
        service = NCMService()
        if not service.is_configured():
            return Response(
                {"detail": "Nepal Can Move courier service is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            track_res = service.track_order(shipment.ncm_order_id)
        except NCMError as exc:
            return Response(
                {"detail": f"Failed to sync courier tracking: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data = track_res.get('data') or {}
        new_courier_status = ""
        history_list = []
        if isinstance(data, dict):
            new_courier_status = str(data.get('status') or data.get('current_status') or shipment.courier_status)
            if 'history' in data and isinstance(data['history'], list):
                history_list = data['history']
        elif isinstance(data, list):
            history_list = data
            if data:
                new_courier_status = str(data[-1].get('status') or shipment.courier_status)

        shipment.apply_status_update(
            new_courier_status=new_courier_status,
            history_list=history_list,
            changed_by=request.user,
            source="admin_courier_sync"
        )
        order.refresh_from_db()
        return Response(OrderSerializer(order).data)


class NCMWebhookView(APIView):
    """
    Webhook endpoint to receive status and tracking updates from Nepal Can Move (NCM).
    Endpoint: POST /api/marketplace/webhooks/ncm/
    Authentication: Validated via NCM_WEBHOOK_SECRET in header or query parameter if configured.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        config = NCMConfiguration.get_settings()
        if not config.webhook_enabled:
            logger.warning("NCM Webhook rejected: webhook processing is disabled in configuration.")
            return Response(
                {'error': 'Webhook processing is currently disabled in courier configuration.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        expected_secret = getattr(settings, 'NCM_WEBHOOK_SECRET', '').strip()
        effective_token = config.get_effective_token()

        if expected_secret:
            provided_secret = (
                request.headers.get('X-NCM-Webhook-Secret') or
                request.META.get('HTTP_X_NCM_WEBHOOK_SECRET') or
                request.headers.get('X-Webhook-Secret') or
                request.META.get('HTTP_X_WEBHOOK_SECRET') or
                request.headers.get('X-Api-Token') or
                request.META.get('HTTP_X_API_TOKEN') or
                request.query_params.get('secret') or
                request.query_params.get('token') or
                request.query_params.get('key') or
                ''
            )
            auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
            if not provided_secret and auth_header:
                for prefix in ('Bearer ', 'Token '):
                    if auth_header.startswith(prefix):
                        provided_secret = auth_header.split(prefix, 1)[1].strip()
                        break
                if not provided_secret:
                    provided_secret = auth_header.strip()

            is_valid_secret = bool(expected_secret and provided_secret and hmac.compare_digest(provided_secret, expected_secret))
            is_valid_token = bool(effective_token and provided_secret and hmac.compare_digest(provided_secret, effective_token))

            if not (is_valid_secret or is_valid_token):
                logger.warning("Unauthorized NCM webhook call attempted")
                return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data
        if not isinstance(payload, dict):
            return Response({'error': 'Invalid payload format: expected JSON object'}, status=status.HTTP_400_BAD_REQUEST)

        # Identifier resolution: ncm_order_id, tracking_id, or vref_id
        ncm_order_id = str(payload.get('order_id') or payload.get('ncm_order_id') or payload.get('orderid') or '').strip()
        tracking_id = str(payload.get('tracking_id') or payload.get('trackingid') or payload.get('track_id') or '').strip()
        vref_id = str(payload.get('vref_id') or payload.get('ref_id') or payload.get('reference_id') or '').strip()

        event_name = str(payload.get('event') or payload.get('status') or payload.get('courier_status') or 'status_update')

        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        # Handle NCM diagnostic / test ping events
        is_test_ping = (
            (not ncm_order_id and not tracking_id and not vref_id)
            or str(payload.get('test') or '').lower() in ['true', '1', 'yes']
            or event_name.lower() in ['test', 'ping', 'webhook_test', 'test_connection']
            or ncm_order_id.lower() in ['test', 'ping', '0']
        )
        if is_test_ping:
            NCMWebhookEvent.objects.create(
                ip_address=ip[:50],
                event_type='test_ping',
                ncm_order_id=ncm_order_id[:100],
                tracking_id=tracking_id[:100],
                payload=payload,
                is_success=True,
                status_code=200,
                error_message="",
            )
            config.last_webhook_received_at = timezone.now()
            config.last_webhook_event = 'test_ping'
            config.last_webhook_error = ''
            config.webhook_registered = True
            config.save(update_fields=['last_webhook_received_at', 'last_webhook_event', 'last_webhook_error', 'webhook_registered'])
            return Response({
                'status': 'ok',
                'message': 'NCM Webhook test received and verified successfully.'
            }, status=status.HTTP_200_OK)

        shipment = None
        if ncm_order_id:
            shipment = CourierShipment.objects.filter(ncm_order_id=ncm_order_id).first()
        if not shipment and tracking_id:
            shipment = CourierShipment.objects.filter(tracking_id=tracking_id).first()
        if not shipment and vref_id:
            shipment = CourierShipment.objects.filter(vref_id=vref_id).first()

        if not shipment:
            logger.warning(
                "NCM Webhook received update for unknown shipment: ncm_order_id=%s, tracking_id=%s, vref_id=%s",
                ncm_order_id, tracking_id, vref_id
            )
            NCMWebhookEvent.objects.create(
                ip_address=ip[:50],
                event_type=event_name[:100],
                ncm_order_id=ncm_order_id[:100],
                tracking_id=tracking_id[:100],
                payload=payload,
                is_success=False,
                status_code=404,
                error_message="Shipment not found",
            )
            config.last_webhook_received_at = timezone.now()
            config.last_webhook_event = event_name[:100]
            config.last_webhook_error = f"Shipment not found (NCM #{ncm_order_id})"
            config.save(update_fields=['last_webhook_received_at', 'last_webhook_event', 'last_webhook_error'])
            return Response({'error': 'Shipment not found'}, status=status.HTTP_404_NOT_FOUND)

        # Status and event extraction
        new_status = payload.get('status') or payload.get('state') or payload.get('courier_status')
        history_entry = payload.get('history') or payload.get('event')

        history_list = None
        if isinstance(history_entry, list):
            history_list = history_entry
        elif isinstance(history_entry, dict):
            existing_history = list(shipment.status_history or [])
            existing_history.append(history_entry)
            history_list = existing_history
        elif new_status:
            existing_history = list(shipment.status_history or [])
            existing_history.append({
                'status': new_status,
                'timestamp': timezone.now().isoformat(),
                'source': 'webhook',
                'remarks': payload.get('remarks') or payload.get('comments') or '',
            })
            history_list = existing_history

        status_changed = shipment.apply_status_update(
            new_courier_status=str(new_status) if new_status else None,
            history_list=history_list,
            tracking_id=tracking_id or None,
            source="ncm_webhook"
        )

        NCMWebhookEvent.objects.create(
            ip_address=ip[:50],
            event_type=event_name[:100],
            ncm_order_id=shipment.ncm_order_id,
            tracking_id=shipment.tracking_id,
            payload=payload,
            is_success=True,
            status_code=200,
        )
        config.last_webhook_received_at = timezone.now()
        config.last_webhook_event = event_name[:100]
        config.last_webhook_error = ""
        config.save(update_fields=['last_webhook_received_at', 'last_webhook_event', 'last_webhook_error'])

        return Response({
            'status': 'success',
            'order_id': shipment.order_id,
            'ncm_order_id': shipment.ncm_order_id,
            'courier_status': shipment.courier_status,
            'order_status': shipment.order.status,
            'order_status_updated': status_changed,
        }, status=status.HTTP_200_OK)


class AdminDeliveryFeeRuleViewSet(viewsets.ModelViewSet):
    queryset = DeliveryFeeRule.objects.all().order_by('-priority', '-created_at')
    serializer_class = DeliveryFeeRuleSerializer
    permission_classes = [IsAdminUser]


class AdminMarketplaceSettingsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        settings = MarketplaceSettings.get_settings()
        return Response(MarketplaceSettingsSerializer(settings).data)

    def patch(self, request):
        settings = MarketplaceSettings.get_settings()
        serializer = MarketplaceSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminListingReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MarketplaceListingReport.objects.all().select_related('listing', 'reporter').order_by('-created_at')
    serializer_class = MarketplaceListingReportSerializer
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        report = self.get_object()
        new_status = request.data.get('status')
        admin_response = request.data.get('admin_response', '').strip()

        if new_status not in ('REVIEWED', 'DISMISSED'):
            return Response({'detail': 'status must be REVIEWED or DISMISSED.'}, status=status.HTTP_400_BAD_REQUEST)

        report.status = new_status
        report.admin_response = admin_response
        report.save(update_fields=['status', 'admin_response', 'updated_at'])
        return Response(MarketplaceListingReportSerializer(report).data)


# ---------------------------------------------------------------------------
# Admin — Nepal Can Move (NCM) Courier Configuration & Management
# ---------------------------------------------------------------------------

class AdminNCMConfigurationView(APIView):
    """
    Manage Nepal Can Move (NCM) courier integration configuration.
    Enforces admin permissions, credential masking, and explicit production confirmation.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        config = NCMConfiguration.get_settings()
        serializer = NCMConfigurationSerializer(config, context={'request': request})
        data = serializer.data

        # Add deployment environment metadata
        render_token = getattr(settings, 'NCM_API_TOKEN', '').strip()
        render_secret = getattr(settings, 'NCM_WEBHOOK_SECRET', '').strip()

        # Webhook URL
        try:
            webhook_url = request.build_absolute_uri(reverse('ncm-webhook'))
        except Exception:
            webhook_url = "/api/marketplace/webhooks/ncm/"

        data['render_env_status'] = {
            'token_in_env': bool(render_token),
            'token_masked': f"{render_token[:4]}****{render_token[-4:]}" if len(render_token) > 8 else ('****' if render_token else ''),
            'webhook_secret_in_env': bool(render_secret),
            'webhook_secret_status': 'Configured in Environment' if render_secret else 'Not Configured',
        }
        data['webhook_endpoint_url'] = webhook_url
        data['fallback_pricing_source'] = "Admin Delivery Fee Rules"

        return Response(data)

    def patch(self, request):
        config = NCMConfiguration.get_settings()
        target_env = request.data.get('environment')

        # Safety Guard: Switching from demo to production requires explicit confirmation
        if target_env == 'production' and config.environment != 'production':
            if not request.data.get('confirm_production'):
                return Response(
                    {
                        "detail": "Switching to Live Production environment requires explicit confirmation. Please confirm that you intend to use Live NCM credentials."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate origin branch if being changed
        new_branch = request.data.get('default_origin_branch')
        if new_branch:
            service = NCMService()
            valid_branch = _validate_ncm_branch(new_branch, service)
            if not valid_branch:
                # If unable to validate due to network, allow known major hubs
                if new_branch.lower() not in ['kathmandu', 'pokhara', 'biratnagar', 'butwal', 'lalitpur', 'bhaktapur']:
                    return Response(
                        {"detail": f"'{new_branch}' is not a verified active NCM origin branch."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        serializer = NCMConfigurationSerializer(
            config,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            saved_config = serializer.save()

            # Record security & audit log
            try:
                from administration.models import AuditLog
                safe_details = {k: v for k, v in request.data.items() if k not in ['new_api_token']}
                if 'new_api_token' in request.data:
                    safe_details['token_updated'] = True
                AuditLog.objects.create(
                    actor=request.user,
                    action='UPDATE_NCM_CONFIGURATION',
                    entity_type='NCMConfiguration',
                    entity_id=str(saved_config.id),
                    details=safe_details
                )
            except Exception as e:
                logger.warning("Failed to record AuditLog for NCM config update: %s", e)

            return Response(NCMConfigurationSerializer(saved_config, context={'request': request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminNCMTestConnectionView(APIView):
    """
    Diagnostic endpoint to test NCM API connectivity and authentication.
    Strictly read-only: checks /v2/branches. Never creates a shipment.
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        service = NCMService()
        result = service.test_connection()

        try:
            from administration.models import AuditLog
            AuditLog.objects.create(
                actor=request.user,
                action='TEST_NCM_CONNECTION',
                entity_type='NCMConfiguration',
                entity_id='1',
                details={
                    'success': result.get('success'),
                    'latency_ms': result.get('latency_ms'),
                    'environment': result.get('environment'),
                }
            )
        except Exception:
            pass

        status_code = status.HTTP_200_OK if result.get('success') else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=status_code)


class AdminNCMBranchesView(APIView):
    """
    Lists available NCM branches, allows refreshing branch cache,
    and enables admin review & updating of branch coordinates and serviceability.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        service = NCMService()
        force_refresh = request.query_params.get('force_refresh', '').lower() in ('1', 'true')
        try:
            from .models import NCMConfiguration
            config = NCMConfiguration.get_settings()
            
            if force_refresh or not NCMBranchRecord.objects.exists():
                branches, meta = service.get_branches(force_refresh=force_refresh, return_meta=True)
                service.sync_branches_to_db(branches)
                source = meta.get('source', 'LIVE_API')
                last_synced = meta.get('last_synced_at')
            else:
                source = config.branch_sync_source or 'DATABASE_CACHE'
                last_synced = config.last_branch_sync_at.isoformat() if config.last_branch_sync_at else None

            records = NCMBranchRecord.objects.all().order_by('province_name', 'district_name', 'name')
            search = (request.query_params.get('search') or '').strip()
            if search:
                records = records.filter(
                    Q(name__icontains=search) |
                    Q(code__icontains=search) |
                    Q(district_name__icontains=search) |
                    Q(municipality__icontains=search)
                )

            status_filter = (request.query_params.get('status') or '').lower()
            if status_filter == 'serviceable':
                records = records.filter(is_serviceable=True)
            elif status_filter == 'unserviceable':
                records = records.filter(is_serviceable=False)

            coord_filter = (request.query_params.get('coord_status') or '').lower()
            if coord_filter == 'verified':
                records = records.filter(is_coordinate_verified=True)
            elif coord_filter == 'unverified':
                records = records.filter(is_coordinate_verified=False)
            elif coord_filter == 'missing':
                records = records.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))

            serializer = NCMBranchRecordSerializer(records, many=True)
            return Response({
                'count': records.count(),
                'branches': serializer.data,
                'source': source,
                'last_synced_at': last_synced,
                'cached': not force_refresh,
            })
        except Exception as e:
            return Response(
                {'detail': f"Failed to fetch NCM branches: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

    def post(self, request):
        """Force refresh branches cache from live NCM API and sync to DB."""
        service = NCMService()
        try:
            from .models import NCMConfiguration
            branches, meta = service.get_branches(force_refresh=True, return_meta=True)
            synced_count = service.sync_branches_to_db(branches)
            records = NCMBranchRecord.objects.all().order_by('province_name', 'district_name', 'name')
            serializer = NCMBranchRecordSerializer(records, many=True)
            
            config = NCMConfiguration.get_settings()
            return Response({
                'success': True,
                'count': records.count(),
                'synced_count': synced_count,
                'branches': serializer.data,
                'source': meta.get('source', 'LIVE_API'),
                'last_synced_at': meta.get('last_synced_at'),
                'refreshed': True,
                'cached': False,
            })
        except Exception as e:
            return Response(
                {'detail': f"Failed to refresh NCM branches: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

    def patch(self, request):
        """
        Admin review & edit coordinates and serviceability for a specific NCM branch.
        Records audit trail in NCMBranchCoordinateAuditLog.
        """
        branch_id = request.data.get('id')
        branch_code = request.data.get('code')

        record = None
        if branch_id:
            record = NCMBranchRecord.objects.filter(id=branch_id).first()
        elif branch_code:
            record = NCMBranchRecord.objects.filter(code=branch_code).first()

        if not record:
            return Response({'detail': "Branch not found."}, status=status.HTTP_404_NOT_FOUND)

        prev_lat = record.latitude
        prev_lon = record.longitude
        prev_src = record.coordinate_source

        new_lat = request.data.get('latitude')
        new_lon = request.data.get('longitude')
        new_source = request.data.get('coordinate_source')
        is_verified = request.data.get('is_coordinate_verified')
        is_serviceable = request.data.get('is_serviceable')
        serviceability_notes = request.data.get('serviceability_notes')
        reason = request.data.get('reason', 'Admin coordinate review')

        with transaction.atomic():
            if new_lat is not None:
                record.latitude = Decimal(str(new_lat)) if str(new_lat).strip() != '' else None
            if new_lon is not None:
                record.longitude = Decimal(str(new_lon)) if str(new_lon).strip() != '' else None
            if new_source is not None:
                record.coordinate_source = str(new_source).strip()
            if is_verified is not None:
                record.is_coordinate_verified = bool(is_verified)
                if record.is_coordinate_verified:
                    record.coordinate_verified_at = timezone.now()
                    record.verified_by = request.user
                else:
                    record.coordinate_verified_at = None
                    record.verified_by = None
            if is_serviceable is not None:
                record.is_serviceable = bool(is_serviceable)
            if serviceability_notes is not None:
                record.serviceability_notes = str(serviceability_notes).strip()

            record.save()

            if (new_lat is not None and prev_lat != record.latitude) or (new_lon is not None and prev_lon != record.longitude) or (new_source and prev_src != record.coordinate_source) or is_verified is not None:
                NCMBranchCoordinateAuditLog.objects.create(
                    branch=record,
                    changed_by=request.user,
                    previous_latitude=prev_lat,
                    previous_longitude=prev_lon,
                    new_latitude=record.latitude,
                    new_longitude=record.longitude,
                    previous_source=prev_src,
                    new_source=record.coordinate_source,
                    reason=str(reason).strip(),
                )

            try:
                from administration.models import AuditLog
                AuditLog.objects.create(
                    actor=request.user,
                    action='UPDATE_NCM_BRANCH_COORDINATES',
                    entity_type='NCMBranchRecord',
                    entity_id=str(record.id),
                    details={
                        'branch_code': record.code,
                        'name': record.name,
                        'latitude': float(record.latitude) if record.latitude else None,
                        'longitude': float(record.longitude) if record.longitude else None,
                        'source': record.coordinate_source,
                        'verified': record.is_coordinate_verified,
                        'serviceable': record.is_serviceable,
                    }
                )
            except Exception:
                pass

        return Response(NCMBranchRecordSerializer(record).data)



class AdminNCMWebhookManagementView(APIView):
    """
    Manages webhook status, registration, and inspection of recent events.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        config = NCMConfiguration.get_settings()
        try:
            webhook_url = request.build_absolute_uri(reverse('ncm-webhook'))
        except Exception:
            webhook_url = "/api/marketplace/webhooks/ncm/"

        secret = getattr(settings, 'NCM_WEBHOOK_SECRET', '').strip()
        recent_events = NCMWebhookEvent.objects.order_by('-received_at')[:15]

        return Response({
            'webhook_endpoint_url': webhook_url,
            'webhook_secret_configured': bool(secret),
            'webhook_secret_status': 'Configured in Environment' if secret else 'Missing (NCM_WEBHOOK_SECRET not set)',
            'webhook_enabled': config.webhook_enabled,
            'webhook_registered': config.webhook_registered,
            'last_webhook_received_at': config.last_webhook_received_at,
            'last_webhook_event': config.last_webhook_event,
            'last_webhook_error': config.last_webhook_error,
            'recent_events': NCMWebhookEventSerializer(recent_events, many=True).data,
        })

    def post(self, request):
        action_name = request.data.get('action')
        config = NCMConfiguration.get_settings()

        if action_name == 'toggle_enabled':
            config.webhook_enabled = not config.webhook_enabled
            config.save(update_fields=['webhook_enabled'])
            return Response({
                'webhook_enabled': config.webhook_enabled,
                'detail': f"Webhook processing {'enabled' if config.webhook_enabled else 'disabled'}.",
            })

        elif action_name == 'toggle_registered':
            config.webhook_registered = not config.webhook_registered
            config.save(update_fields=['webhook_registered'])
            return Response({
                'webhook_registered': config.webhook_registered,
                'detail': f"Webhook registration status updated to {'Registered' if config.webhook_registered else 'Unregistered'}.",
            })

        return Response(
            {'detail': f"Unknown action '{action_name}'. Supported actions: toggle_enabled, toggle_registered."},
            status=status.HTTP_400_BAD_REQUEST
        )


class AdminCourierOverviewView(APIView):
    """
    Aggregated metrics and intelligence for delivery & courier operations.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        config = NCMConfiguration.get_settings()
        try:
            from marketplace.dispatch_service import process_ncm_dispatch_queue
            process_ncm_dispatch_queue(limit=10)
        except Exception:
            pass

        shipments_qs = CourierShipment.objects.filter(provider='NCM')
        total_shipments = shipments_qs.count()

        pending_pickup = shipments_qs.filter(
            courier_status__in=['Order Created', 'order created', 'Pickup Pending', 'pickup pending']
        ).count()

        in_transit = shipments_qs.filter(
            courier_status__in=['Pickup Complete', 'pickup complete', 'In Transit', 'in transit', 'Dispatched', 'dispatched']
        ).count()

        out_for_delivery = shipments_qs.filter(
            courier_status__in=['Out for Delivery', 'out for delivery']
        ).count()

        delivered = shipments_qs.filter(
            courier_status__in=['Delivered', 'delivered']
        ).count()

        returned = shipments_qs.filter(
            courier_status__in=['Return', 'return', 'Cancelled', 'cancelled']
        ).count()

        # Ensure COD orders with shipments have a CODRemittance row
        cod_orders_with_shipment = Order.objects.filter(
            is_cod=True,
            courier_shipment__isnull=False,
            cod_remittance__isnull=True
        ).select_related('courier_shipment')

        for ord_obj in cod_orders_with_shipment:
            CODRemittance.objects.get_or_create(
                order=ord_obj,
                defaults={
                    'courier_shipment': ord_obj.courier_shipment,
                    'expected_amount': ord_obj.cod_remaining_balance,
                    'status': 'VERIFIED' if ord_obj.payment_status == 'PAID' else 'PENDING',
                }
            )

        # COD Remittance Metrics
        pending_remittances = CODRemittance.objects.filter(status='PENDING')
        remittance_pending_count = pending_remittances.count()
        remittance_pending_amount = pending_remittances.aggregate(tot=Sum('expected_amount'))['tot'] or Decimal('0.00')

        verified_remittances = CODRemittance.objects.filter(status='VERIFIED')
        remittance_verified_count = verified_remittances.count()
        remittance_verified_amount = verified_remittances.aggregate(tot=Sum('remitted_amount'))['tot'] or Decimal('0.00')

        discrepancy_count = CODRemittance.objects.filter(status='DISCREPANCY').count()

        # Sync Metrics
        failed_sync_count = CourierSyncLog.objects.filter(status='FAILED').count()
        last_sync_log = CourierSyncLog.objects.order_by('-synced_at').first()

        # Recent shipments
        recent_shipments = shipments_qs.select_related('order', 'order__student')[:6]

        return Response({
            'metrics': {
                'total_shipments': total_shipments,
                'pending_pickup': pending_pickup,
                'in_transit': in_transit,
                'out_for_delivery': out_for_delivery,
                'delivered': delivered,
                'returned': returned,
                'failed_sync_count': failed_sync_count,
                'remittance_pending_count': remittance_pending_count,
                'remittance_pending_amount': float(remittance_pending_amount),
                'remittance_verified_count': remittance_verified_count,
                'remittance_verified_amount': float(remittance_verified_amount),
                'remittance_discrepancy_count': discrepancy_count,
            },
            'configuration': {
                'is_enabled': config.is_enabled,
                'environment': config.environment,
                'connection_status': config.connection_status,
                'last_connection_tested_at': config.last_connection_tested_at,
                'last_connection_latency_ms': config.last_connection_latency_ms,
                'default_origin_branch': config.default_origin_branch,
                'live_rates_enabled': config.live_rates_enabled,
                'fallback_rules_enabled': config.fallback_rules_enabled,
                'auto_sync_enabled': config.auto_sync_enabled,
                'webhook_enabled': config.webhook_enabled,
                'webhook_registered': config.webhook_registered,
                'last_sync_at': config.last_sync_at,
                'token_source': config.get_token_source(),
                'masked_token': config.get_masked_token(),
            },
            'scheduler': {
                'render_cron_job_command': 'python manage.py sync_ncm_shipments --limit 50',
                'celery_worker_present': True,
                'auto_sync_active': config.auto_sync_enabled,
                'last_sync': CourierSyncLogSerializer(last_sync_log).data if last_sync_log else None,
            },
            'recent_shipments': CourierShipmentSerializer(recent_shipments, many=True).data,
        })


class AdminCourierShipmentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Admin management viewset to view, filter, search, and inspect courier shipments.
    """
    queryset = CourierShipment.objects.select_related('order', 'order__student').order_by('-created_at')
    serializer_class = CourierShipmentSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        # Status filter
        status_filter = params.get('status')
        if status_filter:
            status_clean = status_filter.strip().lower()
            if status_clean == 'pending_pickup':
                qs = qs.filter(courier_status__in=['Order Created', 'order created', 'Pickup Pending', 'pickup pending'])
            elif status_clean == 'in_transit':
                qs = qs.filter(courier_status__in=['Pickup Complete', 'pickup complete', 'In Transit', 'in transit', 'Dispatched', 'dispatched'])
            elif status_clean == 'out_for_delivery':
                qs = qs.filter(courier_status__in=['Out for Delivery', 'out for delivery'])
            elif status_clean == 'delivered':
                qs = qs.filter(courier_status__in=['Delivered', 'delivered'])
            elif status_clean == 'returned':
                qs = qs.filter(courier_status__in=['Return', 'return', 'Cancelled', 'cancelled'])
            else:
                qs = qs.filter(courier_status__iexact=status_filter.strip())

        # Branch filter
        branch = params.get('destination_branch')
        if branch:
            qs = qs.filter(destination_branch__iexact=branch.strip())

        # Search query
        search = params.get('search')
        if search:
            q = search.strip()
            qs = qs.filter(
                Q(ncm_order_id__icontains=q) |
                Q(tracking_id__icontains=q) |
                Q(vref_id__icontains=q) |
                Q(destination_branch__icontains=q) |
                Q(order__id__icontains=q) |
                Q(order__student__username__icontains=q) |
                Q(order__student__first_name__icontains=q) |
                Q(order__student__last_name__icontains=q)
            )

        return qs

    @action(detail=True, methods=['post'], url_path='sync')
    def sync_tracking(self, request, pk=None):
        """Sync tracking status from NCM for this shipment."""
        shipment = self.get_object()
        service = NCMService()
        if not service.is_configured():
            return Response(
                {"detail": "NCM courier service is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        try:
            track_res = service.track_order(shipment.ncm_order_id)
        except NCMError as exc:
            return Response(
                {"detail": f"Failed to sync courier tracking: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        data = track_res.get('data') or {}
        new_courier_status = ""
        history_list = []
        if isinstance(data, dict):
            new_courier_status = str(data.get('status') or data.get('current_status') or shipment.courier_status)
            if 'history' in data and isinstance(data['history'], list):
                history_list = data['history']
        elif isinstance(data, list):
            history_list = data
            if data:
                new_courier_status = str(data[-1].get('status') or shipment.courier_status)

        shipment.apply_status_update(
            new_courier_status=new_courier_status,
            history_list=history_list,
            changed_by=request.user,
            source="admin_shipment_sync"
        )
        shipment.refresh_from_db()
        return Response(CourierShipmentSerializer(shipment).data)


class AdminCourierSyncTriggerView(APIView):
    """
    Trigger manual batch synchronization of active NCM shipments and inspect sync logs.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        logs = CourierSyncLog.objects.order_by('-synced_at')[:20]
        return Response(CourierSyncLogSerializer(logs, many=True).data)

    def post(self, request):
        limit = int(request.data.get('limit', 50))
        config = NCMConfiguration.get_settings()
        service = NCMService()

        if not service.is_configured():
            return Response(
                {"detail": "NCM Courier service is not configured with valid credentials."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        active_shipments = list(
            CourierShipment.objects.filter(provider='NCM')
            .exclude(order__status__in=['DELIVERED', 'CANCELLED', 'REFUNDED'])
            .order_by('last_synced_at')[:limit]
        )

        checked_count = len(active_shipments)
        updated_count = 0
        error_count = 0
        error_details = []

        for shipment in active_shipments:
            try:
                tracking_data = service.track_order(shipment.ncm_order_id)
                new_status = None
                history = None
                track_id = None

                if isinstance(tracking_data, dict):
                    inner = tracking_data.get('data') or tracking_data
                    if isinstance(inner, dict):
                        new_status = inner.get('status') or inner.get('state') or inner.get('courier_status')
                        track_id = inner.get('tracking_id') or inner.get('trackingid')
                        history = inner.get('history') or inner.get('timeline')
                    elif isinstance(inner, list) and inner:
                        history = inner
                        new_status = inner[-1].get('status')

                changed = shipment.apply_status_update(
                    new_courier_status=str(new_status) if new_status else None,
                    history_list=history,
                    tracking_id=str(track_id) if track_id else None,
                    changed_by=request.user,
                    source="admin_manual_batch_sync"
                )
                if changed:
                    updated_count += 1
            except Exception as e:
                error_count += 1
                error_details.append({
                    'ncm_order_id': shipment.ncm_order_id,
                    'order_id': shipment.order_id,
                    'error': str(e),
                })

        sync_status = 'SUCCESS'
        if error_count > 0:
            sync_status = 'PARTIAL' if updated_count > 0 or checked_count > error_count else 'FAILED'

        sync_log = CourierSyncLog.objects.create(
            synced_by=request.user,
            trigger_type='manual',
            shipments_checked=checked_count,
            shipments_updated=updated_count,
            errors_count=error_count,
            error_details=error_details[:20],
            status=sync_status,
        )

        config.last_sync_at = timezone.now()
        config.last_sync_status = sync_status
        config.save(update_fields=['last_sync_at', 'last_sync_status'])

        return Response({
            'success': True,
            'status': sync_status,
            'shipments_checked': checked_count,
            'shipments_updated': updated_count,
            'errors_count': error_count,
            'log_id': sync_log.id,
            'timestamp': sync_log.synced_at,
        })


class AdminCODRemittanceViewSet(viewsets.ModelViewSet):
    """
    Safe admin management of Cash on Delivery (COD) collection and courier remittance.
    Ensures that Delivered NCM status NEVER automatically marks payment as PAID.
    Requires explicit admin verification to settle the remaining 85% COD balance.
    """
    queryset = CODRemittance.objects.select_related(
        'order', 'order__student', 'courier_shipment', 'verified_by'
    ).order_by('-created_at')
    serializer_class = CODRemittanceSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        # Auto-create CODRemittance records for any COD orders with courier shipments that lack one
        cod_orders_with_shipment = Order.objects.filter(
            is_cod=True,
            courier_shipment__isnull=False,
            cod_remittance__isnull=True
        ).select_related('courier_shipment')

        for ord_obj in cod_orders_with_shipment:
            CODRemittance.objects.get_or_create(
                order=ord_obj,
                defaults={
                    'courier_shipment': ord_obj.courier_shipment,
                    'expected_amount': ord_obj.cod_remaining_balance,
                    'status': 'VERIFIED' if ord_obj.payment_status == 'PAID' else 'PENDING',
                }
            )

        qs = super().get_queryset()
        params = self.request.query_params

        status_param = params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.strip().upper())

        order_id = params.get('order_id')
        if order_id:
            qs = qs.filter(order_id=order_id)

        search = params.get('search')
        if search:
            q = search.strip()
            qs = qs.filter(
                Q(order__id__icontains=q) |
                Q(reference_number__icontains=q) |
                Q(courier_shipment__ncm_order_id__icontains=q) |
                Q(courier_shipment__tracking_id__icontains=q) |
                Q(order__student__username__icontains=q) |
                Q(order__student__first_name__icontains=q) |
                Q(order__student__last_name__icontains=q)
            )

        return qs

    @action(detail=True, methods=['post'], url_path='verify')
    def verify_remittance(self, request, pk=None):
        """
        Verify that courier has remitted the remaining COD funds to LoksewaAI.
        Transitions order.payment_status to PAID and sets cod_remaining_balance to 0.
        Prevents duplicate remittance verification.
        """
        remittance = self.get_object()

        if remittance.status == 'VERIFIED':
            return Response(
                {"detail": f"Remittance for Order #{remittance.order_id} has already been verified and settled."},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_amount = request.data.get('remitted_amount')
        remitted_amount = None
        if raw_amount is not None:
            try:
                remitted_amount = Decimal(str(raw_amount))
                if remitted_amount < 0:
                    return Response({"detail": "Remitted amount cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
            except Exception:
                return Response({"detail": f"Invalid remitted amount: {raw_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            remitted_amount = remittance.expected_amount

        ref_number = (request.data.get('reference_number') or '').strip()
        notes = (request.data.get('notes') or '').strip()

        try:
            settled = remittance.verify_and_settle(
                verified_by=request.user,
                remitted_amount=remitted_amount,
                reference_number=ref_number,
                notes=notes
            )
            return Response(CODRemittanceSerializer(settled).data, status=status.HTTP_200_OK)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='mark-discrepancy')
    def mark_discrepancy(self, request, pk=None):
        """Flag a financial discrepancy between courier collection and expected remittance."""
        remittance = self.get_object()
        reason = (request.data.get('discrepancy_reason') or '').strip()
        if not reason:
            return Response({"detail": "Discrepancy reason is required."}, status=status.HTTP_400_BAD_REQUEST)

        courier_amount = request.data.get('courier_reported_amount')
        if courier_amount is not None:
            try:
                remittance.courier_reported_amount = Decimal(str(courier_amount))
            except Exception:
                pass

        remittance.status = 'DISCREPANCY'
        remittance.discrepancy_reason = reason
        remittance.notes = (request.data.get('notes') or remittance.notes or '').strip()
        remittance.save(update_fields=['status', 'discrepancy_reason', 'courier_reported_amount', 'notes', 'updated_at'])

        try:
            from administration.models import AuditLog
            AuditLog.objects.create(
                actor=request.user,
                action='FLAG_COD_DISCREPANCY',
                entity_type='Order',
                entity_id=str(remittance.order_id),
                details={
                    'remittance_id': remittance.id,
                    'reason': reason,
                    'expected': float(remittance.expected_amount),
                    'courier_reported': float(remittance.courier_reported_amount) if remittance.courier_reported_amount else None,
                }
            )
        except Exception:
            pass

        return Response(CODRemittanceSerializer(remittance).data)


# ---------------------------------------------------------------------------
# Student — Products (read-only browsing)
# ---------------------------------------------------------------------------

class StudentProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        if not _marketplace_enabled():
            raise PermissionDenied("The marketplace is currently disabled by the administrator.")

        qs = (
            Product.objects
            .filter(is_published=True, listing_status='ACTIVE')
            .select_related('seller', 'target_exam')
            .prefetch_related('images')
            .order_by('-created_at')
        )
        # Filtering
        category = self.request.query_params.get('category')
        condition = self.request.query_params.get('condition')
        seller_type = self.request.query_params.get('seller_type')
        location = self.request.query_params.get('location')
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        search = self.request.query_params.get('search')

        if category:
            qs = qs.filter(category=category)
        if condition:
            qs = qs.filter(condition=condition)
        if seller_type == 'student':
            qs = qs.exclude(seller=None)
        elif seller_type == 'platform':
            qs = qs.filter(seller=None)
        if location:
            qs = qs.filter(location__icontains=location)
        if min_price:
            qs = qs.filter(price__gte=min_price)
        if max_price:
            qs = qs.filter(price__lte=max_price)
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(author__icontains=search) |
                Q(description__icontains=search) |
                Q(publisher__icontains=search)
            )

        # Sorting
        sort = self.request.query_params.get('sort', '-created_at')
        allowed_sorts = ['price', '-price', 'created_at', '-created_at', 'condition', 'title']
        if sort in allowed_sorts:
            qs = qs.order_by(sort)

        return qs


class StudentPaymentMethodViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not _marketplace_enabled():
            raise PermissionDenied("The marketplace is currently disabled by the administrator.")
        return PaymentMethod.objects.filter(is_active=True)


class MarketplacePricingPolicyView(APIView):
    """
    GET /api/marketplace/student/pricing-policy/

    Read-only, any authenticated student. Lets the Sell Book form show the
    real configured commission rate and used-book price cap instead of
    guessing or hardcoding - AdminMarketplaceSettingsView (above) can't be
    used for this since it's IsAdminUser-only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        settings = MarketplaceSettings.get_settings()
        return Response(MarketplacePricingPolicySerializer(settings).data)


class StudentPaymentSubmissionViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSubmissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        return PaymentSubmission.objects.filter(student=self.request.user).order_by('-submitted_at')

    def perform_create(self, serializer):
        if not _marketplace_enabled():
            raise PermissionDenied("The marketplace is currently disabled by the administrator.")

        product = serializer.validated_data.get('product')
        order = serializer.validated_data.get('order')

        if not product and not order:
            raise ValidationError({"detail": "Either product or order must be provided."})

        if product:
            if product.seller and product.seller == self.request.user:
                raise ValidationError({"detail": "You cannot purchase your own listing."})
            pending = PaymentSubmission.objects.filter(
                student=self.request.user, product=product, status='PENDING'
            ).exists()
        else:
            pending = PaymentSubmission.objects.filter(
                student=self.request.user, order=order, status='PENDING'
            ).exists()

        if pending:
            raise ValidationError({"detail": "You already have a pending payment verification for this."})

        if product:
            purchased = Purchase.objects.filter(
                student=self.request.user, product=product, status='ACTIVE'
            ).exists()
            if purchased:
                raise ValidationError({"detail": "You have already purchased this product."})
            expected_amount = product.discount_price if product.discount_price is not None else product.price
            title = product.title
        else:
            if order.student != self.request.user:
                raise PermissionDenied("You do not have permission to submit payment for this order.")
            if order.status not in ['PENDING_PAYMENT', 'PAYMENT_REJECTED', 'PAYMENT_SUBMITTED'] or order.payment_status == 'PAID':
                raise ValidationError({"detail": "Order is not in a payable state."})
            
            # Authoritative calculation of expected_amount:
            if order.is_cod:
                expected_amount = order.cod_advance_required
                is_cod_advance = True
            else:
                expected_amount = (order.total_amount + order.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                is_cod_advance = False
            title = f"Order #{order.id}"
            attempt_number = order.payment_submissions.count() + 1

        if product:
            serializer.save(
                student=self.request.user,
                expected_amount=expected_amount,
                submitted_amount=expected_amount,
                is_cod_advance=False,
                attempt_number=1,
            )
        else:
            serializer.save(
                student=self.request.user,
                expected_amount=expected_amount,
                submitted_amount=expected_amount,
                is_cod_advance=is_cod_advance,
                attempt_number=attempt_number,
            )
            order.status = 'PAYMENT_SUBMITTED'
            order.save(update_fields=['status', 'updated_at'])
            OrderStatusHistory.objects.create(
                order=order,
                previous_status=order.status,
                new_status='PAYMENT_SUBMITTED',
                changed_by=self.request.user,
                note=f"Payment proof submitted for {'COD 15% advance' if is_cod_advance else 'order'} (Attempt #{attempt_number})."
            )

        from core.notification_service import NotificationService
        NotificationService.notify_admins(
            notif_type='payment',
            title='New Payment Awaiting Verification',
            message=(
                f"{self.request.user.get_full_name() or self.request.user.username} submitted "
                f"payment proof for '{title}' (NPR {expected_amount})."
            ),
            action_url='/admin-dashboard/marketplace/payments',
        )
        NotificationService.notify_student_payment_submitted(
            student=self.request.user,
            title_ref=title,
            amount=expected_amount,
            action_url='/student/marketplace/orders' if order else '/student/marketplace',
        )


class StudentPurchaseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PurchaseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Purchase.objects.filter(student=self.request.user, status='ACTIVE').order_by('-created_at')


# ---------------------------------------------------------------------------
# Cart & Order
# ---------------------------------------------------------------------------

class StudentDeliveryAddressViewSet(viewsets.ModelViewSet):
    serializer_class = DeliveryAddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DeliveryAddress.objects.filter(student=self.request.user).order_by('-is_default', '-created_at')

    def perform_create(self, serializer):
        if serializer.validated_data.get('is_default'):
            DeliveryAddress.objects.filter(student=self.request.user).update(is_default=False)
        serializer.save(student=self.request.user)

    def perform_update(self, serializer):
        if serializer.validated_data.get('is_default'):
            DeliveryAddress.objects.filter(student=self.request.user).update(is_default=False)
        serializer.save()

    @action(detail=False, methods=['get'], url_path='profile-address')
    def profile_address(self, request):
        """
        Derives delivery information directly from the authenticated student's registration profile.
        Prioritizes the exact details entered during student signup (name, mobile, district, municipality).
        """
        user = request.user
        profile = getattr(user, 'student_profile', None)
        if profile is None:
            try:
                from support.models import StudentProfile
                profile = StudentProfile.objects.filter(user=user).first()
            except Exception:
                profile = None

        # Registration details entered by the student
        full_name = (user.get_full_name() or user.username or '').strip()
        phone_number = (profile.phone if profile else '') or ''
        district = (profile.permanent_district if profile else '') or ''
        municipality = (profile.permanent_local_level if profile else '') or ''
        province = get_nepal_province_for_district(district) if district else ''

        ward_number = ''
        tole_area = ''
        street_landmark = ''
        delivery_note = ''

        # If student has a saved delivery address, use only supplemental fields (ward, tole, etc.)
        # but NEVER overwrite the student's registered full_name or phone_number.
        saved_addr = DeliveryAddress.objects.filter(student=user).order_by('-is_default', '-created_at').first()
        if saved_addr:
            if not district and saved_addr.district:
                district = saved_addr.district
                province = get_nepal_province_for_district(district) or saved_addr.province or ''
            if not municipality and saved_addr.municipality:
                municipality = saved_addr.municipality
            ward_number = saved_addr.ward_number or ''
            tole_area = saved_addr.tole_area or ''
            street_landmark = saved_addr.street_landmark or ''
            delivery_note = saved_addr.delivery_note or ''

        missing_fields = []
        if not full_name:
            missing_fields.append('full_name')
        if not phone_number:
            missing_fields.append('phone_number')
        if not province:
            missing_fields.append('province')
        if not district:
            missing_fields.append('district')
        if not municipality:
            missing_fields.append('municipality')
        if not ward_number:
            missing_fields.append('ward_number')
        if not tole_area:
            missing_fields.append('tole_area')

        return Response({
            'full_name': full_name,
            'phone_number': phone_number,
            'province': province,
            'district': district,
            'municipality': municipality,
            'ward_number': ward_number,
            'tole_area': tole_area,
            'street_landmark': street_landmark,
            'delivery_note': delivery_note,
            'missing_fields': missing_fields,
            'is_profile_complete': len(missing_fields) == 0,
        })


class CartViewSet(viewsets.ModelViewSet):
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Cart.objects.filter(student=self.request.user)

    def get_object(self):
        cart, _ = Cart.objects.get_or_create(student=self.request.user)
        return cart

    def list(self, request, *args, **kwargs):
        cart = self.get_object()
        serializer = self.get_serializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def add_item(self, request):
        cart = self.get_object()
        product_id = request.data.get('product_id')
        try:
            quantity = int(request.data.get('quantity', 1))
        except (TypeError, ValueError):
            return Response({"detail": "Invalid quantity"}, status=status.HTTP_400_BAD_REQUEST)

        if quantity <= 0:
            return Response({"detail": "Quantity must be at least 1"}, status=status.HTTP_400_BAD_REQUEST)

        if not product_id:
            return Response({"detail": "product_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return Response({"detail": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

        # Only published + ACTIVE listings can be purchased
        if not product.is_published or product.listing_status != 'ACTIVE':
            return Response({"detail": "This product is not available for purchase."}, status=status.HTTP_400_BAD_REQUEST)

        # Prevent self-purchase (seller cannot buy own listing)
        if product.seller and product.seller == request.user:
            return Response(
                {"detail": "You cannot purchase your own listing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        target_quantity = quantity if created else (cart_item.quantity + quantity)
        if product.stock < target_quantity:
            return Response({"detail": f"Not enough stock. Only {product.stock} available."}, status=status.HTTP_400_BAD_REQUEST)

        cart_item.quantity = target_quantity
        cart_item.save()

        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=['post'])
    def remove_item(self, request):
        cart = self.get_object()
        item_id = request.data.get('item_id')
        try:
            item = CartItem.objects.get(id=item_id, cart=cart)
            item.delete()
        except CartItem.DoesNotExist:
            pass
        return Response(CartSerializer(cart).data)


class CartItemDetailView(APIView):
    """PATCH /marketplace/student/cart/items/<id>/ - update one cart item's
    quantity. add_item/remove_item (above) cover add-to-cart and delete; this
    is the missing third piece the frontend (lib/api/marketplace.ts
    updateCartItem) already targets for the +/- quantity controls on the
    cart page, which previously 404'd because this route never existed.

    Kept as a dedicated view rather than a CartViewSet @action because a
    detail route needs the *item* id in the URL, not the cart id (get_object
    on CartViewSet always resolves to the caller's own singleton cart)."""
    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, request, pk):
        # Scoped to the caller's own cart - looking up another student's
        # cart item returns 404, not their cart contents (IDOR-safe).
        try:
            return CartItem.objects.select_related('product', 'cart').get(pk=pk, cart__student=request.user)
        except CartItem.DoesNotExist:
            return None

    def patch(self, request, pk):
        item = self._get_item(request, pk)
        if item is None:
            return Response({'detail': 'Cart item not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            quantity = int(request.data.get('quantity'))
        except (TypeError, ValueError):
            return Response({'detail': 'quantity must be a whole number.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1:
            return Response({'detail': 'quantity must be at least 1. Use remove_item to delete an item.'}, status=status.HTTP_400_BAD_REQUEST)

        product = item.product
        if not product.is_published or product.listing_status != 'ACTIVE':
            return Response({'detail': 'This product is no longer available.'}, status=status.HTTP_400_BAD_REQUEST)
        if product.seller and product.seller == request.user:
            return Response({'detail': 'You cannot purchase your own listing.'}, status=status.HTTP_400_BAD_REQUEST)
        if product.stock < quantity:
            return Response({'detail': f'Only {product.stock} in stock.'}, status=status.HTTP_400_BAD_REQUEST)

        item.quantity = quantity
        item.save(update_fields=['quantity', 'updated_at'])
        return Response(CartSerializer(item.cart).data)

    def delete(self, request, pk):
        # REST-complete alternative to CartViewSet.remove_item's POST action;
        # same ownership scoping and semantics (missing item is a no-op, not an error).
        item = self._get_item(request, pk)
        if item is not None:
            item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MarketplacePagination

    def create(self, request, *args, **kwargs):
        """Standard POST /orders/ delegates directly to the comprehensive checkout handler."""
        return self.checkout(request)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)

    def get_queryset(self):
        return Order.objects.filter(student=self.request.user).prefetch_related(
            'items__product', 'status_history'
        ).order_by('-created_at')

    def _calculate_delivery_fee(self, delivery_address, items=None):
        regional_fee = Decimal('0.00')
        if delivery_address:
            mun = (getattr(delivery_address, 'municipality', '') or '').strip().lower()
            dist = (getattr(delivery_address, 'district', '') or '').strip().lower()
            prov = (getattr(delivery_address, 'province', '') or '').strip().lower()
            rules = DeliveryFeeRule.objects.filter(is_active=True).order_by('-priority', '-created_at')
            for rule in rules:
                r_mun = (rule.municipality or '').strip().lower()
                r_dist = (rule.district or '').strip().lower()
                r_prov = (rule.province or '').strip().lower()
                if r_mun and r_dist and r_prov:
                    if r_mun == mun and r_dist == dist and r_prov == prov:
                        regional_fee = rule.fee
                        break
                elif r_dist and r_prov and not r_mun:
                    if r_dist == dist and r_prov == prov:
                        regional_fee = rule.fee
                        break
                elif r_prov and not r_dist and not r_mun:
                    if r_prov == prov:
                        regional_fee = rule.fee
                        break
                elif not r_prov and not r_dist and not r_mun:
                    regional_fee = rule.fee
                    break

        if items is None:
            user = getattr(self.request, 'user', None)
            if user and user.is_authenticated:
                cart = Cart.objects.filter(student=user).first()
                if cart:
                    items = list(cart.items.select_related('product', 'product__seller').all())

        product_fee = Decimal('0.00')
        if items:
            seller_shipments = {}
            for it in items:
                prod = getattr(it, 'product', it)
                if prod and hasattr(prod, 'delivery_fee'):
                    s_id = getattr(prod, 'seller_id', None)
                    fee = getattr(prod, 'delivery_fee', Decimal('0.00')) or Decimal('0.00')
                    if s_id not in seller_shipments or fee > seller_shipments[s_id]:
                        seller_shipments[s_id] = fee
            product_fee = sum(seller_shipments.values(), Decimal('0.00'))

        calculated = max(regional_fee, product_fee)
        # If still 0, provide safe standard regional baseline:
        # Kathmandu Valley: Rs. 100, Outside Valley: Rs. 150
        if calculated == Decimal('0.00'):
            if delivery_address:
                dist = (getattr(delivery_address, 'district', '') or '').strip().lower()
                mun = (getattr(delivery_address, 'municipality', '') or '').strip().lower()
                if dist in ('kathmandu', 'lalitpur', 'bhaktapur') or any(k in mun for k in ('kathmandu', 'lalitpur', 'bhaktapur')):
                    return Decimal('100.00')
                elif dist:
                    return Decimal('150.00')
            return Decimal('100.00')

        return calculated

    def _validate_ncm_branch(self, branch_name_or_code, service):
        """Validate branch name or code against active NCM branches. Returns canonical branch name or None."""
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
        except Exception as e:
            logger.warning("Error validating NCM branch %s: %s", branch_name_or_code, e)
            return None

    def _resolve_branch_from_address(self, address, service):
        """Match address district/municipality to an active NCM branch using strict local-level-first priority."""
        if not address:
            return None
        dist = str(getattr(address, 'district', '') or '').strip()
        mun = str(getattr(address, 'municipality', '') or '').strip()
        if not dist and not mun:
            return None

        try:
            branches = service.get_branches()
            match_res = match_ncm_branches_for_location(branches, municipality=mun, district=dist)
            return match_res.get("auto_selected")
        except Exception as e:
            logger.warning("Error resolving NCM branch from address: %s", e)
            return None

    @action(detail=False, methods=['get'], url_path='ncm-branches')
    def ncm_branches(self, request):
        """
        Return list of valid, active NCM branches.
        Optionally accepts ?district=... and ?municipality=... to return recommended/suggested branches
        using strict local-level-first search priority:
        Priority 1: Municipality / Local Level (municipality field, branch name, covered areas)
        Priority 2: District fallback (ONLY when Priority 1 yields zero matches)
        """
        config = NCMConfiguration.get_settings()
        service = NCMService()
        fallback_enabled = config.fallback_rules_enabled or getattr(settings, 'NCM_FALLBACK_TO_LOCAL_RULES', True)

        if not config.is_enabled:
            return Response({
                "enabled": False,
                "branches": [],
                "suggested_branches": [],
                "auto_selected": None,
                "recommended_branch": None,
                "match_type": "none",
                "match_priority": 0,
                "message": "NCM courier integration is disabled.",
                "fallback_enabled": fallback_enabled,
            })

        try:
            raw_branches, meta = service.get_branches(return_meta=True)
        except Exception as e:
            logger.warning("Failed to fetch NCM branches: %s", e)
            raw_branches = []
            meta = {"source": "DATABASE_CACHE", "last_synced_at": None, "count": 0}

        formatted = []
        for b in raw_branches:
            name = (b.get('name') or '').strip()
            if not name:
                continue
            raw_areas = b.get('areas_covered') or b.get('coverage') or b.get('covered_areas') or []
            if isinstance(raw_areas, str):
                areas_list = [a.strip() for a in raw_areas.split(',') if a.strip()]
            elif isinstance(raw_areas, list):
                areas_list = [str(a).strip() for a in raw_areas if str(a).strip()]
            else:
                areas_list = []

            formatted.append({
                "code": str(b.get('code') or b.get('pk') or b.get('id') or name),
                "name": name,
                "district_name": (b.get('district_name') or b.get('district') or '').strip(),
                "province_name": (b.get('province_name') or b.get('province') or '').strip(),
                "municipality": (b.get('municipality') or b.get('local_level') or '').strip(),
                "address": (b.get('address') or b.get('location') or '').strip(),
                "contact_number": (b.get('contact_number') or b.get('phone') or b.get('contact') or '').strip(),
                "areas_covered": areas_list,
            })

        q_district = (request.query_params.get('district') or '').strip()
        q_municipality = (request.query_params.get('municipality') or '').strip()
        q_province = (request.query_params.get('province') or '').strip()
        q_tole = (request.query_params.get('tole') or request.query_params.get('area') or '').strip()
        q_lat = request.query_params.get('latitude') or request.query_params.get('lat')
        q_lon = request.query_params.get('longitude') or request.query_params.get('lon')
        q_allow_nearby = request.query_params.get('allow_nearby', '').lower() in ('1', 'true')

        match_res = discover_nearest_ncm_branches(
            formatted,
            municipality=q_municipality,
            district=q_district,
            province=q_province,
            user_lat=q_lat,
            user_lon=q_lon,
            allow_nearby=q_allow_nearby,
            tole=q_tole,
        )

        return Response({
            "enabled": True,
            "source": meta.get("source", "DATABASE_CACHE"),
            "last_synced_at": meta.get("last_synced_at"),
            "count": len(formatted),
            "branches": formatted,
            "suggested_branches": match_res["suggested_branches"],
            "nearby_branches": match_res.get("nearby_branches", []),
            "auto_selected": match_res["auto_selected"],
            "recommended_branch": match_res["recommended_branch"],
            "match_type": match_res["match_type"],
            "match_priority": match_res["match_priority"],
            "message": match_res["message"],
            "search_municipality": match_res["search_municipality"],
            "search_district": match_res["search_district"],
            "search_province": q_province,
            "delivery_anchor": match_res.get("delivery_anchor"),
            "origin_branch": service.default_origin_branch,
            "fallback_enabled": fallback_enabled,
        })

    @action(detail=False, methods=['post'])
    def calculate_fee(self, request):
        delivery_address_id = request.data.get('delivery_address_id')
        product_id = request.data.get('product_id')
        province = request.data.get('province')
        district = request.data.get('district')
        municipality = request.data.get('municipality')
        destination_branch = request.data.get('destination_branch')
        delivery_type = request.data.get('delivery_type') or 'Door2Door'

        delivery_address = None
        if delivery_address_id:
            try:
                delivery_address = DeliveryAddress.objects.get(id=delivery_address_id, student=request.user)
            except DeliveryAddress.DoesNotExist:
                return Response({"detail": "Delivery address not found"}, status=status.HTTP_404_NOT_FOUND)
        elif province or district or municipality:
            class TempAddress:
                pass
            delivery_address = TempAddress()
            delivery_address.province = province or ''
            delivery_address.district = district or ''
            delivery_address.municipality = municipality or ''
        else:
            return Response({"detail": "Delivery address is required"}, status=status.HTTP_400_BAD_REQUEST)

        items = None
        if product_id:
            try:
                prod = Product.objects.get(id=product_id)
                items = [prod]
            except Product.DoesNotExist:
                pass

        config = NCMConfiguration.get_settings()
        fallback_allowed = config.fallback_rules_enabled or getattr(settings, 'NCM_FALLBACK_TO_LOCAL_RULES', False)
        service = NCMService()

        # If NCM is configured and enabled, attempt live courier rate
        if service.is_configured() and config.is_enabled and config.live_rates_enabled:
            target_branch = destination_branch
            if not target_branch and delivery_address:
                target_branch = self._resolve_branch_from_address(delivery_address, service)

            if target_branch:
                canonical_branch = self._validate_ncm_branch(target_branch, service)
                if not canonical_branch:
                    return Response(
                        {"detail": f"Destination branch '{target_branch}' is not a valid NCM branch."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    rate_res = service.calculate_rate(
                        destination_branch=canonical_branch,
                        source_branch=service.default_origin_branch,
                        delivery_type=delivery_type,
                    )
                    return Response({
                        "delivery_fee": rate_res["charge"],
                        "fee_source": "ncm",
                        "destination_branch": canonical_branch,
                        "delivery_type": delivery_type,
                        "fallback_applied": False,
                    })
                except Exception as err:
                    logger.warning("NCM rate calculation error: %s; falling back to regional delivery rules.", err)
                    fallback_fee = self._calculate_delivery_fee(delivery_address, items=items)
                    return Response({
                        "delivery_fee": fallback_fee,
                        "fee_source": "rule_fallback",
                        "destination_branch": canonical_branch,
                        "delivery_type": delivery_type,
                        "fallback_applied": True,
                        "fallback_reason": str(err),
                    })
            else:
                # No branch specified or matched: calculate delivery fee from address
                fee = self._calculate_delivery_fee(delivery_address, items=items)
                return Response({
                    "delivery_fee": fee,
                    "fee_source": "rule_fallback",
                    "destination_branch": destination_branch or "",
                    "delivery_type": delivery_type,
                    "fallback_applied": True,
                    "fallback_reason": "Regional delivery rules applied for address.",
                })
        else:
            # NCM not configured or live rates disabled: apply regional delivery rules
            fee = self._calculate_delivery_fee(delivery_address, items=items)
            return Response({
                "delivery_fee": fee,
                "fee_source": "rule_fallback",
                "destination_branch": destination_branch or "",
                "delivery_type": delivery_type,
                "fallback_applied": True,
                "fallback_reason": "Verified regional delivery rules applied."
            })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Allow a student to cancel their own order while it is still unpaid (PENDING_PAYMENT)."""
        order = self.get_object()
        if order.student != request.user:
            raise PermissionDenied("You can only cancel your own orders.")
        if order.payment_status in ['PARTIALLY_PAID', 'PAID']:
            return Response(
                {"detail": "This order cannot be cancelled directly because a payment has already been verified. "
                           "Please contact support. Note: the 15% COD advance is non-refundable per marketplace policy."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status != 'PENDING_PAYMENT':
            return Response(
                {"detail": f"Order cannot be cancelled in status '{order.status}'. Only unpaid orders can be cancelled directly."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            if order.payment_status in ['PARTIALLY_PAID', 'PAID']:
                return Response(
                    {"detail": "Order payment has already been verified."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if order.status != 'PENDING_PAYMENT':
                return Response({"detail": "Order status has changed."}, status=status.HTTP_400_BAD_REQUEST)

            order.status = 'CANCELLED'
            order.save(update_fields=['status', 'updated_at'])

            OrderStatusHistory.objects.create(
                order=order,
                previous_status='PENDING_PAYMENT',
                new_status='CANCELLED',
                changed_by=request.user,
                note='Cancelled by student before payment',
            )

            # Return stock
            for item in order.items.select_related('product').all():
                p = Product.objects.select_for_update().get(pk=item.product_id)
                p.stock += item.quantity
                if p.stock > 0 and p.listing_status == 'SOLD':
                    p.listing_status = 'ACTIVE'
                    p.is_published = True
                p.save(update_fields=['stock', 'listing_status', 'is_published'])

            order.items.update(fulfillment_status='CANCELLED', payout_status='CANCELLED')

        from core.notification_service import NotificationService
        status_display = dict(Order.STATUS_CHOICES).get('CANCELLED', 'Cancelled')
        NotificationService.notify_order_status(
            student=order.student,
            order_id=order.id,
            status_display=status_display,
            action_url='/student/marketplace/orders',
        )

        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='hold')
    def hold(self, request, pk=None):
        """Allow a customer to put an eligible order on hold.

        Eligible statuses: CONFIRMED, PROCESSING.
        Important: the 15% COD advance is NON-REFUNDABLE. This is recorded in
        the status history but the advance is never auto-deducted here. Any
        exceptional refund requires an explicit admin-authorised action.
        """
        order = self.get_object()
        if order.student != request.user:
            raise PermissionDenied("You can only modify your own orders.")

        # Only confirmed / processing orders can be held by the customer
        if order.status not in ['CONFIRMED', 'PROCESSING']:
            return Response(
                {
                    "detail": (
                        f"Order cannot be put on hold in status '{order.status}'. "
                        "Only confirmed or processing orders are eligible."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get('reason') or '').strip()

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            # Re-check inside the lock
            if order.status not in ['CONFIRMED', 'PROCESSING']:
                return Response(
                    {"detail": "Order status has changed. Cannot place on hold."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.utils import timezone as tz
            old_status = order.status
            order.status = 'ON_HOLD'
            order.hold_reason = reason
            order.held_at = tz.now()
            order.save(update_fields=['status', 'hold_reason', 'held_at', 'updated_at'])

            # Build history note including the non-refundable advance policy reminder
            advance_note = ''
            if order.is_cod and order.payment_status == 'PARTIALLY_PAID':
                advance_note = (
                    f" Note: the 15% COD advance (NPR {order.cod_advance_paid}) "
                    "is non-refundable per marketplace policy."
                )
            history_note = f"Order placed on hold by customer.{' Reason: ' + reason if reason else ''}{advance_note}"

            OrderStatusHistory.objects.create(
                order=order,
                previous_status=old_status,
                new_status='ON_HOLD',
                changed_by=request.user,
                note=history_note,
            )

        # Notify admins about the hold
        from core.notification_service import NotificationService
        student_name = request.user.get_full_name() or request.user.username
        NotificationService.notify_admins(
            notif_type='order',
            title='Order Placed On Hold by Customer',
            message=(
                f"{student_name} placed Order #{order.id} on hold."
                + (f" Reason: {reason}" if reason else "")
                + (
                    f" COD advance (NPR {order.cod_advance_paid}) is non-refundable."
                    if order.is_cod and order.payment_status == 'PARTIALLY_PAID'
                    else ""
                )
            ),
            action_url='/admin-dashboard/marketplace/orders',
        )
        # Notify the customer
        NotificationService.notify_order_status(
            student=order.student,
            order_id=order.id,
            status_display='On Hold',
            action_url='/student/marketplace/orders',
        )

        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='switch-payment-mode')
    def switch_payment_mode(self, request, pk=None):
        """Allow a student to switch between full prepaid payment and COD (15% advance)."""
        order = self.get_object()
        if order.student != request.user:
            raise PermissionDenied("You can only modify your own orders.")
        if order.status not in ['PENDING_PAYMENT', 'PAYMENT_SUBMITTED'] or order.payment_status == 'PAID':
            return Response({"detail": "This order is not eligible for payment modification."}, status=status.HTTP_400_BAD_REQUEST)

        if order.payment_submissions.filter(status='PENDING').exists():
            return Response({"detail": "Cannot switch payment mode while a payment verification is pending review."}, status=status.HTTP_400_BAD_REQUEST)

        target_mode = str(request.data.get('payment_mode') or '').upper().strip()
        if target_mode not in ['PREPAID', 'COD']:
            return Response({"detail": "Invalid payment mode. Choose 'PREPAID' or 'COD'."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            final_total = (order.total_amount + order.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if target_mode == 'COD':
                order.is_cod = True
                order.payment_method_type = 'COD'
                order.cod_advance_rate = Decimal('15.00')
                order.cod_advance_required = (final_total * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                order.cod_remaining_balance = (final_total - (order.cod_advance_paid if order.cod_advance_paid > 0 else order.cod_advance_required)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                order.is_cod = False
                order.payment_method_type = 'PREPAID'
                order.cod_advance_rate = Decimal('0.00')
                order.cod_advance_required = Decimal('0.00')
                order.cod_remaining_balance = Decimal('0.00')

            order.save(update_fields=['is_cod', 'payment_method_type', 'cod_advance_rate', 'cod_advance_required', 'cod_remaining_balance', 'updated_at'])

            OrderStatusHistory.objects.create(
                order=order,
                previous_status=order.status,
                new_status=order.status,
                changed_by=request.user,
                note=f"Payment mode switched to {target_mode} by student."
            )

        return Response(OrderSerializer(order).data)

    @action(detail=False, methods=['post'])
    def checkout(self, request):
        try:
            return self._perform_checkout(request)
        except ValidationError as ve:
            detail = ve.detail if hasattr(ve, 'detail') else str(ve)
            return Response(detail if isinstance(detail, dict) else {"detail": str(detail)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as pe:
            return Response({"detail": str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as exc:
            logger.exception("Order checkout error for user %s: %s", getattr(request.user, 'id', None), exc)
            return Response({"detail": f"Could not complete checkout: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST)

    def _perform_checkout(self, request):
        if not _marketplace_enabled():
            raise PermissionDenied("The marketplace is currently disabled by the administrator.")

        delivery_address_id = request.data.get('delivery_address_id')
        delivery_address_data = request.data.get('delivery_address')
        shipping_address_raw = request.data.get('shipping_address')
        contact_number_raw = request.data.get('contact_number')

        # Automatically deserialize JSON string if passed as stringified JSON
        if isinstance(delivery_address_data, str) and delivery_address_data.strip():
            try:
                import json
                delivery_address_data = json.loads(delivery_address_data)
            except Exception:
                pass

        # If address fields are passed directly in request.data, assemble delivery_address_data
        if (not delivery_address_data or not isinstance(delivery_address_data, dict)) and isinstance(request.data, dict):
            if any(k in request.data for k in ('district', 'province', 'municipality', 'tole_area', 'ward_number')):
                delivery_address_data = {
                    k: request.data.get(k)
                    for k in ('full_name', 'phone_number', 'province', 'district', 'municipality', 'ward_number', 'tole_area', 'street_landmark', 'delivery_note')
                    if k in request.data
                }

        if delivery_address_id is not None:
            try:
                delivery_address_id = int(delivery_address_id)
            except (ValueError, TypeError):
                delivery_address_id = None

        delivery_address = None
        shipping_address_snapshot = {}
        delivery_fee = Decimal('0.00')

        if delivery_address_id:
            try:
                delivery_address = DeliveryAddress.objects.get(id=delivery_address_id, student=request.user)
            except DeliveryAddress.DoesNotExist:
                return Response({"detail": "Delivery address not found"}, status=status.HTTP_404_NOT_FOUND)

            shipping_address_snapshot = {
                'full_name': delivery_address.full_name,
                'phone_number': delivery_address.phone_number,
                'province': delivery_address.province,
                'district': delivery_address.district,
                'municipality': delivery_address.municipality,
                'ward_number': delivery_address.ward_number,
                'tole_area': delivery_address.tole_area,
                'street_landmark': delivery_address.street_landmark or '',
                'delivery_note': delivery_address.delivery_note or '',
            }
            shipping_address_str = (
                f"{delivery_address.full_name}\n{delivery_address.phone_number}\n"
                f"{delivery_address.province}, {delivery_address.district}, "
                f"{delivery_address.municipality}-{delivery_address.ward_number}\n"
                f"{delivery_address.tole_area}"
            )
            if delivery_address.street_landmark:
                shipping_address_str += f"\nLandmark: {delivery_address.street_landmark}"
            if delivery_address.delivery_note:
                shipping_address_str += f"\nNote: {delivery_address.delivery_note}"
            
            contact_number_str = delivery_address.phone_number

        elif delivery_address_data and isinstance(delivery_address_data, dict):
            required_fields = ['full_name', 'phone_number', 'province', 'district', 'municipality', 'ward_number', 'tole_area']
            missing = [f for f in required_fields if not str(delivery_address_data.get(f) or '').strip()]
            if missing:
                return Response(
                    {"detail": f"Please provide required delivery fields: {', '.join(missing)}.", "missing_fields": missing},
                    status=status.HTTP_400_BAD_REQUEST
                )

            save_to_addresses = request.data.get('save_to_addresses', True)
            if save_to_addresses:
                delivery_address = DeliveryAddress.objects.create(
                    student=request.user,
                    full_name=delivery_address_data['full_name'].strip(),
                    phone_number=delivery_address_data['phone_number'].strip(),
                    province=delivery_address_data['province'].strip(),
                    district=delivery_address_data['district'].strip(),
                    municipality=delivery_address_data['municipality'].strip(),
                    ward_number=str(delivery_address_data['ward_number']).strip(),
                    tole_area=delivery_address_data['tole_area'].strip(),
                    street_landmark=(delivery_address_data.get('street_landmark') or '').strip(),
                    delivery_note=(delivery_address_data.get('delivery_note') or '').strip(),
                    is_default=bool(request.data.get('is_default', False))
                )
            else:
                class TempAddr:
                    pass
                delivery_address = TempAddr()
                for k, v in delivery_address_data.items():
                    setattr(delivery_address, k, v)

            shipping_address_snapshot = {
                'full_name': delivery_address_data['full_name'].strip(),
                'phone_number': delivery_address_data['phone_number'].strip(),
                'province': delivery_address_data['province'].strip(),
                'district': delivery_address_data['district'].strip(),
                'municipality': delivery_address_data['municipality'].strip(),
                'ward_number': str(delivery_address_data['ward_number']).strip(),
                'tole_area': delivery_address_data['tole_area'].strip(),
                'street_landmark': (delivery_address_data.get('street_landmark') or '').strip(),
                'delivery_note': (delivery_address_data.get('delivery_note') or '').strip(),
            }
            shipping_address_str = (
                f"{shipping_address_snapshot['full_name']}\n{shipping_address_snapshot['phone_number']}\n"
                f"{shipping_address_snapshot['province']}, {shipping_address_snapshot['district']}, "
                f"{shipping_address_snapshot['municipality']}-{shipping_address_snapshot['ward_number']}\n"
                f"{shipping_address_snapshot['tole_area']}"
            )
            if shipping_address_snapshot['street_landmark']:
                shipping_address_str += f"\nLandmark: {shipping_address_snapshot['street_landmark']}"
            if shipping_address_snapshot['delivery_note']:
                shipping_address_str += f"\nNote: {shipping_address_snapshot['delivery_note']}"
            contact_number_str = shipping_address_snapshot['phone_number']

        else:
            if not shipping_address_raw or not contact_number_raw:
                # Automatic fallback to student's saved delivery addresses or registration profile
                saved_fallback = DeliveryAddress.objects.filter(student=request.user).order_by('-is_default', '-created_at').first()
                if saved_fallback:
                    delivery_address = saved_fallback
                    contact_number_str = saved_fallback.phone_number
                    shipping_address_str = (
                        f"{saved_fallback.full_name}\n{saved_fallback.phone_number}\n"
                        f"{saved_fallback.province}, {saved_fallback.district}, "
                        f"{saved_fallback.municipality}-{saved_fallback.ward_number}\n"
                        f"{saved_fallback.tole_area}"
                    )
                    shipping_address_snapshot = {
                        'full_name': saved_fallback.full_name,
                        'phone_number': saved_fallback.phone_number,
                        'province': saved_fallback.province,
                        'district': saved_fallback.district,
                        'municipality': saved_fallback.municipality,
                        'ward_number': saved_fallback.ward_number,
                        'tole_area': saved_fallback.tole_area,
                    }
                else:
                    prof = getattr(request.user, 'student_profile', None)
                    phone_val = (prof.phone if prof else '') or ''
                    dist_val = (prof.permanent_district if prof else '') or ''
                    mun_val = (prof.permanent_local_level if prof else '') or ''
                    prov_val = get_nepal_province_for_district(dist_val) if dist_val else ''
                    name_val = (request.user.get_full_name() or request.user.username or '').strip()

                    if phone_val and (dist_val or mun_val):
                        contact_number_str = phone_val
                        shipping_address_str = f"{name_val}\n{phone_val}\n{prov_val}, {dist_val}, {mun_val}".strip()
                        shipping_address_snapshot = {
                            'full_name': name_val,
                            'phone_number': phone_val,
                            'province': prov_val,
                            'district': dist_val,
                            'municipality': mun_val,
                        }
                    else:
                        return Response({"detail": "Delivery address or shipping details are required. Please complete your delivery address."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                shipping_address_str = shipping_address_raw
                contact_number_str = contact_number_raw
                shipping_address_snapshot = {
                    'shipping_address': shipping_address_raw,
                    'contact_number': contact_number_raw
                }

        from core.notification_service import NotificationService

        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(student=request.user).first()
            if not cart or not cart.items.exists():
                return Response({"detail": "Cart is empty"}, status=status.HTTP_400_BAD_REQUEST)

            # Lock products for update and validate
            cart_items = list(cart.items.select_related('product', 'product__seller').all())
            for item in cart_items:
                # Prevent self-purchase (double-check at checkout)
                if item.product.seller and item.product.seller == request.user:
                    raise ValidationError({"detail": f"You cannot purchase your own listing: {item.product.title}"})
                # Stock check with lock
                product = Product.objects.select_for_update().get(pk=item.product.pk)
                if not product.is_published or product.listing_status not in ('ACTIVE',):
                    raise ValidationError({"detail": f"{product.title} is no longer available."})
                if product.stock < item.quantity:
                    raise ValidationError({"detail": f"Not enough stock for {product.title}"})
                product.stock -= item.quantity
                # Auto-mark as SOLD when stock reaches 0 (especially important for single-copy used books)
                if product.stock == 0:
                    product.listing_status = 'SOLD'
                    product.is_published = False
                product.save(update_fields=['stock', 'listing_status', 'is_published'])

            total_amount = sum(item.product.final_price * item.quantity for item in cart_items)
            
            # --- SERVER-SIDE DELIVERY FEE & NCM REVALIDATION ---
            destination_branch_req = request.data.get('destination_branch')
            delivery_type_req = str(request.data.get('delivery_type') or 'Door2Door').strip()
            config = NCMConfiguration.get_settings()
            fallback_allowed = config.fallback_rules_enabled or getattr(settings, 'NCM_FALLBACK_TO_LOCAL_RULES', False)

            service = NCMService()
            delivery_fee = Decimal('0.00')
            fee_source = 'ncm'
            fallback_applied = False
            validated_branch_name = None

            if service.is_configured() and config.is_enabled and config.live_rates_enabled:
                target_branch = destination_branch_req
                if not target_branch and delivery_address:
                    target_branch = self._resolve_branch_from_address(delivery_address, service)

                if target_branch:
                    validated_branch_name = self._validate_ncm_branch(target_branch, service)
                    if not validated_branch_name:
                        raise ValidationError({"detail": f"Destination branch '{target_branch}' is not a valid NCM branch."})

                    try:
                        rate_res = service.calculate_rate(
                            destination_branch=validated_branch_name,
                            source_branch=service.default_origin_branch,
                            delivery_type=delivery_type_req,
                        )
                        delivery_fee = Decimal(str(rate_res["charge"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        fee_source = 'ncm'
                    except Exception as err:
                        logger.warning("NCM rate calculation error at checkout (%s); applying regional delivery rules.", err)
                        delivery_fee = self._calculate_delivery_fee(delivery_address, cart_items)
                        fee_source = 'rule_fallback'
                        fallback_applied = True
                else:
                    delivery_fee = self._calculate_delivery_fee(delivery_address, cart_items)
                    fee_source = 'rule_fallback'
                    fallback_applied = True
            else:
                delivery_fee = self._calculate_delivery_fee(delivery_address, cart_items)
                fee_source = 'rule_fallback'
                fallback_applied = True

            final_total = (total_amount + delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            payment_mode = str(request.data.get('payment_mode') or 'PREPAID').upper().strip()
            is_cod = (payment_mode == 'COD')

            if is_cod:
                cod_advance_rate = Decimal('15.00')
                cod_advance_required = (final_total * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                cod_advance_paid = Decimal('0.00')
                cod_remaining_balance = (final_total - cod_advance_required).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                payment_method_type = 'COD'
            else:
                cod_advance_rate = Decimal('0.00')
                cod_advance_required = Decimal('0.00')
                cod_advance_paid = Decimal('0.00')
                cod_remaining_balance = Decimal('0.00')
                payment_method_type = 'PREPAID'

            # Update shipping snapshot with verified courier details
            shipping_address_snapshot['ncm_destination_branch'] = validated_branch_name or ''
            shipping_address_snapshot['ncm_delivery_type'] = delivery_type_req
            shipping_address_snapshot['delivery_fee_source'] = fee_source
            shipping_address_snapshot['delivery_fee_quoted'] = float(delivery_fee)
            shipping_address_snapshot['fallback_applied'] = fallback_applied

            order = Order.objects.create(
                student=request.user,
                total_amount=total_amount,
                delivery_fee=delivery_fee,
                payment_method_type=payment_method_type,
                is_cod=is_cod,
                cod_advance_rate=cod_advance_rate,
                cod_advance_required=cod_advance_required,
                cod_advance_paid=cod_advance_paid,
                cod_remaining_balance=cod_remaining_balance,
                payment_status='UNPAID',
                delivery_address_ref=delivery_address if isinstance(delivery_address, DeliveryAddress) else None,
                shipping_address=shipping_address_str,
                contact_number=contact_number_str,
                shipping_address_snapshot=shipping_address_snapshot,
                status='PENDING_PAYMENT',
            )

            commission_pct = MarketplaceSettings.get_settings().platform_commission_percentage

            for item in cart_items:
                price = item.product.final_price
                line_total = price * item.quantity
                commission = ((line_total * Decimal(str(commission_pct))) / Decimal('100.00')).quantize(Decimal('0.01'))
                seller_earning = (line_total - commission).quantize(Decimal('0.01'))
                seller_name = (
                    item.product.seller.get_full_name() or item.product.seller.username
                    if item.product.seller else "LoksewaAI Platform"
                )

                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    price=price,
                    commission_amount=commission,
                    seller_earning=seller_earning,
                    snapshot_product_name=item.product.title,
                    snapshot_seller_name=seller_name,
                )

            OrderStatusHistory.objects.create(
                order=order,
                previous_status='',
                new_status='PENDING_PAYMENT',
                changed_by=request.user,
                note=f"Order created via Checkout ({'COD with 15% Advance' if is_cod else 'Full Online Payment'})",
            )

            # Clear cart
            cart.items.all().delete()

        # Notify sellers that their book was purchased
        try:
            seller_ids = set(
                order.items.filter(product__seller__isnull=False)
                .values_list('product__seller_id', flat=True)
            )
            from core.models import User as UserModel
            for seller in UserModel.objects.filter(id__in=seller_ids):
                NotificationService.notify_book_sold(seller, order)
        except Exception as notif_err:
            logger.warning(f"Failed to notify seller for order {order.id}: {notif_err}")

        # Notify student that their order was placed (awaiting payment).
        # Admin notification is NOT sent here — the order is PENDING_PAYMENT with no
        # verified payment. Admin email fires in AdminPaymentSubmissionViewSet.review()
        # only after the required advance/full payment is successfully verified.
        try:
            from core.email_notification_service import EmailNotificationService
            EmailNotificationService.send_student_order_created_email(order)
        except Exception as email_err:
            logger.warning(f"Failed to dispatch order created email for order #{order.id}: {email_err}")

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Seller Listing ViewSet (student creates/manages their own listings)
# ---------------------------------------------------------------------------

# Fields that trigger re-review if changed on an ACTIVE listing
_REVIEW_FIELDS = {
    'price', 'condition', 'description', 'title',
    'author', 'publisher', 'isbn', 'edition', 'condition_details', 'published_date', 'total_pages',
}

MAX_IMAGES_DEFAULT = 6


class SellerListingViewSet(viewsets.ModelViewSet):
    serializer_class = SellerListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Product.objects
            .filter(seller=self.request.user)
            .prefetch_related('images')
            .order_by('-created_at')
        )

    def _check_marketplace_open(self):
        if not _marketplace_enabled():
            raise PermissionDenied("The marketplace is currently disabled.")
        settings = MarketplaceSettings.get_settings()
        if not settings.allow_student_listings:
            raise PermissionDenied("Student listings are currently disabled by the administrator.")

    def perform_create(self, serializer):
        self._check_marketplace_open()
        product = serializer.save(
            seller=self.request.user,
            listing_status='PENDING_REVIEW',
            is_published=False,
        )
        self._handle_images(product)

        from core.notification_service import NotificationService
        NotificationService.notify_listing_submitted(self.request.user, product)
        NotificationService.notify_admins(
            notif_type='system',
            title='New Student Listing Pending Review',
            message=(
                f"{self.request.user.get_full_name() or self.request.user.username} "
                f"submitted a new listing: \"{product.title}\" — Rs. {product.price}."
            ),
            action_url='/admin-dashboard/marketplace',
        )

    def perform_update(self, serializer):
        instance = self.get_object()
        # Determine if re-review is needed
        needs_rereview = (
            instance.listing_status == 'ACTIVE'
            and any(field in serializer.validated_data for field in _REVIEW_FIELDS)
        )
        extra = {}
        if needs_rereview:
            extra = {'listing_status': 'PENDING_REVIEW', 'is_published': False}
        product = serializer.save(**extra)
        self._handle_images(product)

    def _handle_images(self, product):
        """Process uploaded images from the request."""
        request = self.request
        settings = MarketplaceSettings.get_settings()
        max_images = settings.max_listing_images

        existing_count = product.images.count()

        # Support multiple image files: images[0], images[1], ...
        # Also support labels: image_labels[0], image_labels[1], ...
        uploaded = request.FILES.getlist('images')
        labels = request.POST.getlist('image_labels')

        if uploaded:
            remaining_slots = max(0, max_images - existing_count)
            for i, img_file in enumerate(uploaded[:remaining_slots]):
                label = labels[i] if i < len(labels) else 'other'
                is_primary = (existing_count == 0 and i == 0)
                ProductImage.objects.create(
                    product=product,
                    image=img_file,
                    label=label,
                    is_primary=is_primary,
                )

        # Allow deletion of specific images
        delete_ids = request.data.getlist('delete_image_ids')
        if delete_ids:
            product.images.filter(id__in=delete_ids, product__seller=request.user).delete()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only allow deletion of PENDING_REVIEW, REJECTED, DRAFT, ARCHIVED listings
        if instance.listing_status in ('ACTIVE', 'SOLD'):
            return Response(
                {"detail": "Cannot delete an active or sold listing. Archive it instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        product = self.get_object()
        if product.listing_status == 'SOLD':
            return Response({"detail": "Sold listings cannot be archived."}, status=status.HTTP_400_BAD_REQUEST)
        product.listing_status = 'ARCHIVED'
        product.is_published = False
        product.save(update_fields=['listing_status', 'is_published', 'updated_at'])
        return Response(SellerListingSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def resubmit(self, request, pk=None):
        """Re-submit a REJECTED listing for admin review after making corrections."""
        product = self.get_object()
        if product.listing_status != 'REJECTED':
            return Response(
                {"detail": "Only rejected listings can be resubmitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        product.listing_status = 'PENDING_REVIEW'
        product.rejection_reason = ''
        product.save(update_fields=['listing_status', 'rejection_reason', 'updated_at'])

        from core.notification_service import NotificationService
        NotificationService.notify_admins(
            notif_type='system',
            title='Listing Resubmitted for Review',
            message=(
                f"{request.user.get_full_name() or request.user.username} "
                f"resubmitted \"{product.title}\" for review."
            ),
            action_url='/admin-dashboard/marketplace',
        )
        return Response(SellerListingSerializer(product, context={'request': request}).data)


# ---------------------------------------------------------------------------
# Seller Sales ViewSet
# ---------------------------------------------------------------------------

class SellerSalesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/marketplace/student/my-sales/
    Returns orders that contain at least one item sold by the current user.
    Only shows the seller's own items within each order, not full order detail.
    """
    serializer_class = SellerSaleSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MarketplacePagination

    def get_queryset(self):
        return (
            Order.objects
            .filter(items__product__seller=self.request.user)
            .distinct()
            .prefetch_related('items__product', 'student')
            .order_by('-created_at')
        )


# ---------------------------------------------------------------------------
# Student Listing Report
# ---------------------------------------------------------------------------

class StudentListingReportViewSet(viewsets.ModelViewSet):
    serializer_class = MarketplaceListingReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']  # no update/delete for students

    def get_queryset(self):
        return MarketplaceListingReport.objects.filter(reporter=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        listing = serializer.validated_data['listing']
        # Cannot report own listing
        if listing.seller == self.request.user:
            raise ValidationError({"detail": "You cannot report your own listing."})
        # Already reported?
        if MarketplaceListingReport.objects.filter(listing=listing, reporter=self.request.user).exists():
            raise ValidationError({"detail": "You have already reported this listing."})
        serializer.save(reporter=self.request.user)
        from core.notification_service import NotificationService
        NotificationService.notify_admins(
            notif_type='system',
            title='Listing Reported',
            message=(
                f"\"{listing.title}\" was reported by "
                f"{self.request.user.get_full_name() or self.request.user.username}. "
                f"Reason: {serializer.validated_data.get('reason')}"
            ),
            action_url='/admin-dashboard/marketplace',
        )


# ---------------------------------------------------------------------------
# Trust & Safety (Student)
# ---------------------------------------------------------------------------

class StudentReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Review.objects.filter(buyer=self.request.user)

    def perform_create(self, serializer):
        order_item = serializer.validated_data['order_item']
        
        if order_item.order.student != self.request.user:
            raise PermissionDenied("You can only review your own purchases.")
        
        if order_item.fulfillment_status != 'DELIVERED':
            raise ValidationError("You can only review items that have been delivered.")
            
        if order_item.product.seller == self.request.user:
            raise ValidationError("You cannot review your own product.")

        if Review.objects.filter(order_item=order_item).exists():
            raise ValidationError("A review already exists for this item.")
            
        review = serializer.save(
            buyer=self.request.user,
            seller=order_item.product.seller,
            product=order_item.product
        )
        from core.notification_service import NotificationService
        NotificationService.notify_review_received(review.seller, review.product, review.rating)


class StudentDisputeViewSet(viewsets.ModelViewSet):
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Q
        return Dispute.objects.filter(Q(buyer=self.request.user) | Q(seller=self.request.user))

    def perform_create(self, serializer):
        order_item = serializer.validated_data['order_item']
        
        if order_item.order.student != self.request.user:
            raise PermissionDenied("You can only open disputes for your own purchases.")

        if Dispute.objects.filter(order_item=order_item).exists():
            raise ValidationError("A dispute already exists for this item.")

        with transaction.atomic():
            dispute = serializer.save(
                buyer=self.request.user,
                seller=order_item.product.seller
            )
            order_item.payout_status = 'ON_HOLD'
            order_item.save(update_fields=['payout_status'])

        from core.notification_service import NotificationService
        NotificationService.notify_dispute_opened(dispute.seller, dispute.order_item.product)
        NotificationService.notify_payout_held(dispute.seller, dispute.order_item.order.id)
        NotificationService.notify_admins(
            notif_type='system',
            title='New Dispute Opened',
            message=f"Dispute #{dispute.id} was opened for Order #{dispute.order_item.order.id}",
            action_url='/admin-dashboard/marketplace/trust',
        )

# ---------------------------------------------------------------------------
# Trust & Safety (Admin)
# ---------------------------------------------------------------------------

class AdminReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all().order_by('-created_at')
    serializer_class = ReviewSerializer
    permission_classes = [IsAdminUser]


class AdminDisputeViewSet(viewsets.ModelViewSet):
    queryset = Dispute.objects.all().order_by('-created_at')
    serializer_class = DisputeSerializer
    permission_classes = [IsAdminUser]
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        dispute = self.get_object()
        new_status = request.data.get('status')
        resolution = request.data.get('resolution', '')
        
        if new_status not in ['RESOLVED', 'REJECTED']:
            return Response({"detail": "Invalid status."}, status=400)
            
        with transaction.atomic():
            dispute.status = new_status
            dispute.resolution = resolution
            dispute.resolved_by = request.user
            dispute.resolved_at = timezone.now()
            dispute.save()
            
            if new_status == 'RESOLVED':
                dispute.order_item.payout_status = 'ELIGIBLE'
                dispute.order_item.save(update_fields=['payout_status'])
            elif new_status == 'REJECTED':
                dispute.order_item.payout_status = 'ELIGIBLE'
                dispute.order_item.save(update_fields=['payout_status'])
                
        from core.notification_service import NotificationService
        NotificationService.notify_dispute_status_changed(dispute.buyer, dispute.order_item.product, dispute.get_status_display())
        NotificationService.notify_dispute_status_changed(dispute.seller, dispute.order_item.product, dispute.get_status_display())
        
        return Response(DisputeSerializer(dispute).data)


# ---------------------------------------------------------------------------
# S2S Payouts (Student)
# ---------------------------------------------------------------------------
from .models import PayoutAccount, SellerPayout
from .serializers import PayoutAccountSerializer, SellerPayoutSerializer, AdminSellerPayoutSerializer, SellerBalanceSerializer
from django.db.models import Sum

class StudentPayoutAccountViewSet(viewsets.ModelViewSet):
    serializer_class = PayoutAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PayoutAccount.objects.filter(seller=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(seller=self.request.user)


class StudentPayoutViewSet(viewsets.ModelViewSet):
    serializer_class = SellerPayoutSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MarketplacePagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return SellerPayout.objects.filter(seller=self.request.user).order_by('-created_at')

    @action(detail=False, methods=['get'])
    def balance(self, request):
        seller = request.user
        settings = MarketplaceSettings.get_settings()
        
        # Calculate Total Earnings
        earnings_agg = OrderItem.objects.filter(
            product__seller=seller, 
            payout_status__in=['ELIGIBLE', 'PROCESSING', 'PAID']
        ).aggregate(total=Sum('seller_earning'))
        total_earnings = earnings_agg['total'] or Decimal('0.00')

        # Calculate Pending Payouts
        pending_agg = SellerPayout.objects.filter(
            seller=seller, 
            status__in=['PENDING', 'APPROVED', 'PROCESSING']
        ).aggregate(total=Sum('requested_amount'))
        pending_payouts = pending_agg['total'] or Decimal('0.00')

        # Calculate Paid Out
        paid_agg = SellerPayout.objects.filter(
            seller=seller, 
            status='PAID'
        ).aggregate(total=Sum('requested_amount'))
        paid_out = paid_agg['total'] or Decimal('0.00')

        available_balance = total_earnings - pending_payouts - paid_out

        data = {
            'total_earnings': total_earnings,
            'pending_payouts': pending_payouts,
            'paid_out': paid_out,
            'available_balance': available_balance,
            'minimum_payout_amount': settings.minimum_payout_amount
        }
        return Response(SellerBalanceSerializer(data).data)

    @action(detail=False, methods=['post'])
    def request(self, request):
        amount_str = request.data.get('requested_amount')
        payout_account_id = request.data.get('payout_account_id')

        if not amount_str or not payout_account_id:
            return Response({"detail": "requested_amount and payout_account_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = Decimal(str(amount_str))
        except Exception:
            return Response({"detail": "Invalid amount."}, status=status.HTTP_400_BAD_REQUEST)

        settings = MarketplaceSettings.get_settings()
        if amount < settings.minimum_payout_amount:
            return Response({"detail": f"Minimum payout amount is Rs. {settings.minimum_payout_amount}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payout_account = PayoutAccount.objects.get(id=payout_account_id, seller=request.user)
        except PayoutAccount.DoesNotExist:
            return Response({"detail": "Invalid payout account."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Lock the seller to prevent double payout request race conditions
            from core.models import User as UserModel
            UserModel.objects.select_for_update().get(id=request.user.id)

            earnings_agg = OrderItem.objects.filter(
                product__seller=request.user, 
                payout_status__in=['ELIGIBLE', 'PROCESSING', 'PAID']
            ).aggregate(total=Sum('seller_earning'))
            total_earnings = earnings_agg['total'] or Decimal('0.00')

            pending_agg = SellerPayout.objects.filter(
                seller=request.user, 
                status__in=['PENDING', 'APPROVED', 'PROCESSING']
            ).aggregate(total=Sum('requested_amount'))
            pending_payouts = pending_agg['total'] or Decimal('0.00')

            paid_agg = SellerPayout.objects.filter(
                seller=request.user, 
                status='PAID'
            ).aggregate(total=Sum('requested_amount'))
            paid_out = paid_agg['total'] or Decimal('0.00')

            available_balance = total_earnings - pending_payouts - paid_out

            if amount > available_balance:
                return Response({"detail": "Requested amount exceeds available balance."}, status=status.HTTP_400_BAD_REQUEST)

            payout = SellerPayout.objects.create(
                seller=request.user,
                payout_account=payout_account,
                requested_amount=amount,
                status='PENDING'
            )

        from core.notification_service import NotificationService
        NotificationService.notify_payout_requested(request.user, amount)

        return Response(SellerPayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# S2S Payouts (Admin)
# ---------------------------------------------------------------------------

class AdminPayoutViewSet(viewsets.ModelViewSet):
    queryset = SellerPayout.objects.all().select_related('seller', 'payout_account', 'processed_by').order_by('-created_at')
    serializer_class = AdminSellerPayoutSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MarketplacePagination

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        payout = self.get_object()
        new_status = request.data.get('status')
        admin_note = request.data.get('admin_note', payout.admin_note)
        rejection_reason = request.data.get('rejection_reason', payout.rejection_reason)
        transaction_reference = request.data.get('transaction_reference', payout.transaction_reference)

        valid_statuses = [choice[0] for choice in SellerPayout.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == 'REJECTED' and not rejection_reason:
            return Response({"detail": "Rejection reason is required when rejecting a payout."}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == 'PAID' and not transaction_reference:
            return Response({"detail": "Transaction reference is required when marking as PAID."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            payout.status = new_status
            payout.admin_note = admin_note
            payout.rejection_reason = rejection_reason
            payout.transaction_reference = transaction_reference
            payout.processed_by = request.user
            payout.processed_at = timezone.now()
            payout.save()

        from core.notification_service import NotificationService
        if new_status == 'APPROVED':
            NotificationService.notify_payout_approved(payout.seller, payout.requested_amount)
        elif new_status == 'PROCESSING':
            NotificationService.notify_payout_processing(payout.seller, payout.requested_amount)
        elif new_status == 'PAID':
            method = payout.payout_account.get_method_display() if payout.payout_account else 'Unknown'
            NotificationService.notify_payout_paid(payout.seller, payout.requested_amount, method, transaction_reference)
        elif new_status == 'REJECTED':
            NotificationService.notify_payout_rejected(payout.seller, payout.requested_amount, rejection_reason)
        elif new_status == 'FAILED':
            NotificationService.notify_payout_failed(payout.seller, payout.requested_amount, admin_note)

        return Response(AdminSellerPayoutSerializer(payout).data)
