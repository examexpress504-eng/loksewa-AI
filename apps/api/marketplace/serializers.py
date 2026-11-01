# pyrefly: ignore [missing-import]

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from .models import (

    Product, PaymentMethod, PaymentSubmission, Purchase, ProductImage,

    Cart, CartItem, Order, OrderItem, DeliveryAddress, DeliveryFeeRule,

    OrderStatusHistory, MarketplaceSettings, MarketplaceListingReport,

    Review, Dispute, DisputeEvidence, PayoutAccount, SellerPayout, CourierShipment,
    NCMConfiguration, NCMWebhookEvent, CourierSyncLog, CODRemittance,
    NCMBranchRecord, NCMBranchCoordinateAuditLog,

)

from core.models import User

from exams.models import Exam

class DeliveryAddressSerializer(serializers.ModelSerializer):

    class Meta:

        model = DeliveryAddress

        fields = '__all__'

        read_only_fields = ('student', 'created_at', 'updated_at')

class ProductImageSerializer(serializers.ModelSerializer):

    class Meta:

        model = ProductImage

        fields = ('id', 'product', 'image', 'label', 'is_primary', 'created_at')

        read_only_fields = ('created_at',)

class SafeSellerSerializer(serializers.ModelSerializer):

    """Public-safe seller info: never exposes email, phone, address."""

    member_since = serializers.SerializerMethodField()

    average_rating = serializers.FloatField(read_only=True, required=False)

    total_reviews = serializers.IntegerField(read_only=True, required=False)

    class Meta:

        model = User

        fields = ('id', 'first_name', 'member_since', 'average_rating', 'total_reviews')

    def get_member_since(self, obj):

        return obj.date_joined.strftime('%b %Y') if obj.date_joined else None

class OptionalIntegerField(serializers.IntegerField):

    def to_internal_value(self, data):

        if data == '' or data is None:

            return None

        return super().to_internal_value(data)

class ProductSerializer(serializers.ModelSerializer):

    description = serializers.CharField(required=False, allow_blank=True, default='')

    published_date = serializers.CharField(required=False, allow_blank=True, default='')

    total_pages = OptionalIntegerField(required=False, allow_null=True)

    final_price = serializers.ReadOnlyField()

    delivery_fee = serializers.DecimalField(

        max_digits=10, decimal_places=2, required=False, min_value=Decimal('0.00'),

        default=Decimal('0.00'),

        error_messages={'min_value': 'Delivery fee cannot be negative.'}

    )

    is_seller_listing = serializers.ReadOnlyField()

    images = ProductImageSerializer(many=True, read_only=True)

    seller_details = serializers.SerializerMethodField()

    condition_display = serializers.SerializerMethodField()

    category_display = serializers.SerializerMethodField()

    listing_status_display = serializers.SerializerMethodField()

    average_rating = serializers.FloatField(read_only=True, required=False)

    total_reviews = serializers.IntegerField(read_only=True, required=False)

    class Meta:

        model = Product

        exclude = ()

        read_only_fields = ('created_at', 'updated_at')

    def get_seller_details(self, obj):

        if obj.seller:

            return {

                'id': obj.seller.id,

                'first_name': obj.seller.first_name,

                'member_since': obj.seller.date_joined.strftime('%b %Y') if obj.seller.date_joined else None,

            }

        return None

    def get_condition_display(self, obj):

        return obj.get_condition_display() if obj.condition else None

    def get_category_display(self, obj):

        return obj.get_category_display()

    def get_listing_status_display(self, obj):

        return obj.get_listing_status_display()

class SellerListingSerializer(serializers.ModelSerializer):

    """

    Serializer for student sellers — strips fields that only admins/platform

    should control (is_published, listing_status, seller, rejection_reason).

    Images are handled separately via the view.

    Pricing rule (client requirement): a used book's asking price

    (`price`) must not exceed `max_used_book_price_percent` (default 65%,

    admin-configurable via MarketplaceSettings) of its `marked_price` (the

    price printed on the book). This is the authoritative check - the

    frontend's live calculator is a convenience, not the enforcement point,

    so a direct API call can't bypass it.

    """

    description = serializers.CharField(required=False, allow_blank=True, default='')

    published_date = serializers.CharField(required=False, allow_blank=True, default='')

    total_pages = OptionalIntegerField(required=False, allow_null=True)

    final_price = serializers.ReadOnlyField()

    is_seller_listing = serializers.ReadOnlyField()

    images = ProductImageSerializer(many=True, read_only=True)

    seller_details = serializers.SerializerMethodField()

    condition_display = serializers.SerializerMethodField()

    listing_status_display = serializers.SerializerMethodField()

    # Both re-declared as required + > 0: the model allows price=0/marked_price=null

    # for other product flows (e.g. admin-entered platform stock), but a

    # student listing must always state both to make the 65% rule meaningful.

    marked_price = serializers.DecimalField(

        max_digits=10, decimal_places=2, required=True,

        min_value=Decimal('0.01'),

        error_messages={'min_value': 'Marked price must be greater than 0.'},

    )

    price = serializers.DecimalField(

        max_digits=10, decimal_places=2, required=True,

        min_value=Decimal('0.01'),

        error_messages={'min_value': 'Offer price must be greater than 0.'},

    )

    class Meta:

        model = Product

        exclude = ()

        read_only_fields = (

            'seller', 'is_published', 'listing_status', 'rejection_reason',

            'delivery_fee', 'created_at', 'updated_at',

        )

    def validate(self, data):

        # On PATCH, a field not included in this request falls back to the

        # existing instance value so partial updates still get checked

        # against the real current pair, not a missing one.

        marked_price = data.get('marked_price', getattr(self.instance, 'marked_price', None))

        price = data.get('price', getattr(self.instance, 'price', None))

        if marked_price is not None and price is not None:

            # Same str()-roundtrip as OrderViewSet's commission calculation

            # (marketplace/views.py) - MarketplaceSettings fields can come

            # back as a plain float (e.g. right after get_or_create() applies

            # the model's Python-level default, before any DB round-trip

            # coerces it), and Decimal * float raises TypeError.

            max_percent = Decimal(str(MarketplaceSettings.get_settings().max_used_book_price_percent))

            max_allowed = (marked_price * max_percent / Decimal('100')).quantize(Decimal('0.01'))

            if price > max_allowed:

                raise serializers.ValidationError({

                    'price': [

                        f"Offer price cannot exceed {max_percent.normalize()}% of the marked price "

                        f"(maximum allowed: Rs. {max_allowed})."

                    ]

                })

        return data

    def get_seller_details(self, obj):

        if obj.seller:

            return {

                'id': obj.seller.id,

                'first_name': obj.seller.first_name,

                'member_since': obj.seller.date_joined.strftime('%b %Y') if obj.seller.date_joined else None,

            }

        return None

    def get_condition_display(self, obj):

        return obj.get_condition_display() if obj.condition else None

    def get_listing_status_display(self, obj):

        return obj.get_listing_status_display()

class PaymentMethodSerializer(serializers.ModelSerializer):

    class Meta:

        model = PaymentMethod

        fields = '__all__'

        read_only_fields = ('updated_at',)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        qr = ret.get('qr_image')
        if qr and instance.qr_image:
            from core.storage_backends import _parse_file_id
            file_id = _parse_file_id(instance.qr_image.name)
            if file_id:
                ret['qr_image_direct'] = f'https://lh3.googleusercontent.com/d/{file_id}'
        return ret

class StudentBasicSerializer(serializers.ModelSerializer):

    class Meta:

        model = User

        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class PaymentSubmissionSerializer(serializers.ModelSerializer):

    student_details = StudentBasicSerializer(source='student', read_only=True)

    product_details = serializers.SerializerMethodField()

    product_name = serializers.SerializerMethodField()

    product_id = serializers.SerializerMethodField()

    payment_method_details = PaymentMethodSerializer(source='payment_method', read_only=True)

    order_details = serializers.SerializerMethodField()

    class Meta:

        model = PaymentSubmission

        fields = '__all__'

        read_only_fields = (

            'student', 'status', 'rejection_reason', 'submitted_at', 'verified_at',

            'verified_by', 'expected_amount', 'submitted_amount', 'is_cod_advance', 'attempt_number'

        )

    def get_product_id(self, obj):

        if obj.product_id:

            return obj.product_id

        if obj.order:

            first_item = obj.order.items.first()

            if first_item and first_item.product_id:

                return first_item.product_id

        return None

    def get_product_details(self, obj):

        if obj.product:

            return ProductSerializer(obj.product, context=self.context).data

        if obj.order:

            first_item = obj.order.items.select_related('product', 'product__seller').first()

            if first_item:

                if first_item.product:

                    return ProductSerializer(first_item.product, context=self.context).data

                return {

                    'id': first_item.product_id or 0,

                    'title': first_item.snapshot_product_name or f"Order #{obj.order.id} Item",

                    'price': str(first_item.price),

                    'final_price': str(first_item.price),

                    'cover_image': None,

                }

        return None

    def get_product_name(self, obj):

        if obj.product:

            return obj.product.title

        if obj.order:

            items = list(obj.order.items.select_related('product').all())

            if not items:

                return f"Order #{obj.order.id}"

            first_name = items[0].snapshot_product_name or (items[0].product.title if items[0].product else f"Product #{items[0].product_id or items[0].id}")

            if len(items) == 1:

                return f"{first_name} (x{items[0].quantity})"

            return f"{first_name} (+{len(items) - 1} more items)"

        return "Unknown Item"

    def get_order_details(self, obj):

        if not obj.order:

            return None

        order = obj.order

        def _cover_url(prod):

            if not prod or not prod.cover_image:

                return None

            try:

                u = prod.cover_image.url
                if u:
                    if 'localhost' in u or '127.0.0.1' in u:
                        from urllib.parse import urlparse
                        u = urlparse(u).path
                    req = self.context.get('request')
                    return req.build_absolute_uri(u) if req else u

            except Exception:

                return None

        return {

            'id': order.id,

            'total_amount': str(order.total_amount),

            'delivery_fee': str(order.delivery_fee),

            'final_total': str((order.total_amount + order.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),

            'is_cod': order.is_cod,

            'payment_method_type': order.payment_method_type,

            'cod_advance_required': str(order.cod_advance_required),

            'cod_advance_paid': str(order.cod_advance_paid),

            'cod_remaining_balance': str(order.cod_remaining_balance),

            'status': order.status,

            'payment_status': order.payment_status,

            'shipping_address': order.shipping_address,

            'shipping_address_snapshot': order.shipping_address_snapshot,

            'contact_number': order.contact_number,

            'items': [

                {

                    'id': it.id,

                    'product_id': it.product_id,

                    'title': it.snapshot_product_name or (it.product.title if it.product else 'Item'),

                    'quantity': it.quantity,

                    'price': str(it.price),

                    'total_price': str((it.price * it.quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),

                    'cover_image': _cover_url(it.product),

                    'category': it.product.category if it.product else None,

                    'condition': it.product.condition if it.product else None,

                    'seller_name': it.snapshot_seller_name or (

                        (it.product.seller.get_full_name() or it.product.seller.username)

                        if (it.product and it.product.seller) else "LoksewaAI"

                    ),

                }

                for it in order.items.select_related('product', 'product__seller').all()

            ]

        }

    def validate_transaction_id(self, value):

        value = value.strip()

        if not value:

            raise serializers.ValidationError("Transaction ID cannot be empty.")

        if len(value) > 255:

            raise serializers.ValidationError("Transaction ID is too long.")

        return value

class PaymentSubmissionAdminReviewSerializer(serializers.ModelSerializer):

    class Meta:

        model = PaymentSubmission

        fields = ['status', 'rejection_reason']

class PurchaseSerializer(serializers.ModelSerializer):

    product_details = ProductSerializer(source='product', read_only=True)

    payment_submission_details = PaymentSubmissionSerializer(source='payment_submission', read_only=True)

    class Meta:

        model = Purchase

        fields = '__all__'

        read_only_fields = ('student', 'created_at', 'approved_at', 'status', 'amount_paid')

class CartItemSerializer(serializers.ModelSerializer):

    product_details = ProductSerializer(source='product', read_only=True)

    class Meta:

        model = CartItem

        fields = '__all__'

        read_only_fields = ('cart', 'created_at', 'updated_at')

class CartSerializer(serializers.ModelSerializer):

    items = CartItemSerializer(many=True, read_only=True)

    class Meta:

        model = Cart

        fields = '__all__'

        read_only_fields = ('student', 'created_at', 'updated_at')

class OrderItemSerializer(serializers.ModelSerializer):

    product_details = ProductSerializer(source='product', read_only=True)

    class Meta:

        model = OrderItem

        fields = '__all__'

        read_only_fields = ('order',)

class OrderStatusHistorySerializer(serializers.ModelSerializer):

    changed_by_name = serializers.SerializerMethodField()

    class Meta:

        model = OrderStatusHistory

        fields = '__all__'

    def get_changed_by_name(self, obj):

        if obj.changed_by:

            return obj.changed_by.get_full_name() or obj.changed_by.username

        return "System"


class CourierShipmentSerializer(serializers.ModelSerializer):
    mapped_status = serializers.CharField(source='get_mapped_order_status', read_only=True)

    class Meta:
        model = CourierShipment
        fields = '__all__'


class OrderSerializer(serializers.ModelSerializer):

    items = OrderItemSerializer(many=True, read_only=True)

    delivery_address_details = DeliveryAddressSerializer(source='delivery_address_ref', read_only=True)

    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    courier_shipment = CourierShipmentSerializer(read_only=True)

    payment_mode = serializers.CharField(source='payment_method_type', read_only=True)
    final_total = serializers.SerializerMethodField()
    latest_payment_submission = serializers.SerializerMethodField()
    can_retry_payment = serializers.SerializerMethodField()
    lifecycle_status = serializers.SerializerMethodField()
    dispatch_observability = serializers.SerializerMethodField()

    class Meta:

        model = Order

        fields = '__all__'

        read_only_fields = (

            'student', 'total_amount', 'delivery_fee', 'status',

            'payment_status', 'payment_method_type', 'is_cod',

            'cod_advance_rate', 'cod_advance_required', 'cod_advance_paid',

            'cod_remaining_balance', 'shipping_address_snapshot',

            'hold_reason', 'held_at', 'advance_forfeited',

            'ncm_dispatch_status', 'ncm_dispatch_attempts',
            'ncm_dispatch_last_error', 'ncm_dispatch_next_retry',
            'ncm_dispatch_last_attempt_at',

            'created_at', 'updated_at'

        )

    def get_final_total(self, obj):

        return (obj.total_amount + obj.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def get_latest_payment_submission(self, obj):
        submissions = getattr(obj, '_prefetched_objects_cache', {}).get('payment_submissions')
        if submissions is not None:
            sorted_submissions = sorted(
                submissions,
                key=lambda s: s.submitted_at or s.created_at if hasattr(s, 'created_at') else s.id,
                reverse=True
            )
            latest = sorted_submissions[0] if sorted_submissions else None
        else:
            latest = obj.payment_submissions.select_related('payment_method').order_by('-submitted_at').first()

        if not latest:
            return None

        return {
            'id': latest.id,
            'status': latest.status,
            'rejection_reason': latest.rejection_reason,
            'transaction_id': latest.transaction_id,
            'expected_amount': str(latest.expected_amount),
            'submitted_amount': str(latest.submitted_amount),
            'is_cod_advance': latest.is_cod_advance,
            'attempt_number': latest.attempt_number,
            'submitted_at': latest.submitted_at.isoformat() if latest.submitted_at else None,
            'verified_at': latest.verified_at.isoformat() if latest.verified_at else None,
            'payment_method_id': latest.payment_method_id,
            'payment_method_name': latest.payment_method.display_name if latest.payment_method else None,
        }

    def get_can_retry_payment(self, obj):
        if obj.status in ['CANCELLED', 'REFUNDED', 'DELIVERED', 'ON_HOLD']:
            return False

        if obj.payment_status == 'PAID':
            return False

        submissions = getattr(obj, '_prefetched_objects_cache', {}).get('payment_submissions')
        if submissions is not None:
            if any(s.status == 'PENDING' for s in submissions):
                return False
        else:
            if obj.payment_submissions.filter(status='PENDING').exists():
                return False

        return True

    def get_lifecycle_status(self, obj) -> str:
        """
        Computes distinct high-level order & courier lifecycle status:
        PENDING_PAYMENT, PAYMENT_VERIFIED, DISPATCH_QUEUED, DISPATCH_PROCESSING,
        DISPATCH_FAILED, MANUAL_REVIEW_REQUIRED, NCM_ORDER_CREATED, IN_TRANSIT,
        DELIVERED, REMITTANCE_CONFIRMED.
        """
        shipment = getattr(obj, 'courier_shipment', None)
        if obj.is_cod and shipment and obj.status == 'DELIVERED':
            remittance = getattr(obj, 'cod_remittance', None)
            if (remittance and remittance.status == 'VERIFIED') or obj.payment_status == 'PAID':
                return 'REMITTANCE_CONFIRMED'
            return 'DELIVERED'

        if shipment:
            if obj.status == 'DELIVERED':
                return 'DELIVERED'
            if obj.status in ('SHIPPED', 'OUT_FOR_DELIVERY') or shipment.courier_status.lower() in ('in transit', 'shipped', 'picked up', 'out for delivery', 'at hub'):
                return 'IN_TRANSIT'
            return 'NCM_ORDER_CREATED'

        if obj.ncm_dispatch_status == 'MANUAL_REVIEW_REQUIRED':
            return 'MANUAL_REVIEW_REQUIRED'
        if obj.ncm_dispatch_status == 'FAILED':
            return 'DISPATCH_FAILED'
        if obj.ncm_dispatch_status == 'CREATING':
            return 'DISPATCH_PROCESSING'
        if obj.ncm_dispatch_status == 'QUEUED':
            return 'DISPATCH_QUEUED'

        if obj.payment_status in ('PAID', 'PARTIALLY_PAID') and obj.status in ('CONFIRMED', 'PROCESSING'):
            return 'PAYMENT_VERIFIED'

        return 'PENDING_PAYMENT'

    def get_dispatch_observability(self, obj) -> Dict[str, Any]:
        """Provides complete administrative observability telemetry."""
        shipment = getattr(obj, 'courier_shipment', None)
        latest_job = getattr(obj, '_prefetched_objects_cache', {}).get('ncm_dispatch_jobs')
        if latest_job is not None:
            job = latest_job[0] if len(latest_job) > 0 else None
        else:
            job = obj.ncm_dispatch_jobs.order_by('-created_at').first() if hasattr(obj, 'ncm_dispatch_jobs') else None

        queue_ts = job.created_at.isoformat() if job else None
        worker_ts = (
            job.last_attempt_at.isoformat() if job and job.last_attempt_at else
            obj.ncm_dispatch_last_attempt_at.isoformat() if obj.ncm_dispatch_last_attempt_at else None
        )

        ncm_auth_status = self.context.get('ncm_auth_status') if isinstance(self.context, dict) else None
        if ncm_auth_status is None:
            ncm_auth_status = getattr(self, '_cached_ncm_auth_status', None)
        if ncm_auth_status is None:
            from marketplace.models import NCMConfiguration
            config = NCMConfiguration.get_settings()
            ncm_auth_status = config.connection_status if config else 'untested'
            self._cached_ncm_auth_status = ncm_auth_status

        return {
            'lifecycle_status': self.get_lifecycle_status(obj),
            'payment_verification_status': (
                'Verified (15% Advance)' if obj.is_cod and obj.payment_status == 'PARTIALLY_PAID' else
                'Verified (100% Full Payment)' if obj.payment_status == 'PAID' else
                'Pending Verification'
            ),
            'dispatch_job_status': (
                'COMPLETED' if shipment else
                job.status if job else
                obj.ncm_dispatch_status
            ),
            'queue_timestamp': queue_ts,
            'worker_execution_timestamp': worker_ts,
            'ncm_auth_status': ncm_auth_status,
            'dispatch_attempt_count': obj.ncm_dispatch_attempts or (job.attempts if job else 0),
            'ncm_order_id': shipment.ncm_order_id if shipment else None,
            'tracking_reference': shipment.tracking_id if shipment else None,
            'last_failure_reason': obj.ncm_dispatch_last_error or (job.last_error if job else ''),
            'next_retry_status': (
                obj.ncm_dispatch_next_retry.isoformat() if obj.ncm_dispatch_next_retry else
                'Manual review required' if obj.ncm_dispatch_status == 'MANUAL_REVIEW_REQUIRED' else
                'None scheduled'
            ),
        }

class DeliveryFeeRuleSerializer(serializers.ModelSerializer):

    class Meta:

        model = DeliveryFeeRule

        fields = '__all__'

        read_only_fields = ('created_at', 'updated_at')

# ---------------------------------------------------------------------------

# S2S: Seller sales view — a safe view of orders containing seller's products

# ---------------------------------------------------------------------------

class SellerOrderItemSerializer(serializers.ModelSerializer):

    """Order item serializer for the seller's sales view — only exposes

    the seller's own product; does NOT expose other order items."""

    product_details = serializers.SerializerMethodField()

    class Meta:

        model = OrderItem

        fields = (

            'id', 'product', 'product_details', 'quantity', 'price',

            'commission_amount', 'seller_earning', 

            'fulfillment_status', 'payout_status', 'snapshot_product_name'

        )

    def get_product_id(self, obj):

        if obj.product_id:

            return obj.product_id

        if obj.order:

            first_item = obj.order.items.first()

            if first_item and first_item.product_id:

                return first_item.product_id

        return None

    def get_product_details(self, obj):

        return {

            'id': obj.product.id,

            'title': obj.product.title,

            'cover_image': (

                self.context['request'].build_absolute_uri(
                    obj.product.cover_image.url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '')
                )
                if obj.product.cover_image and obj.product.cover_image.url else None

            ),

        }

class SellerSaleSerializer(serializers.ModelSerializer):

    """Order summary for the seller dashboard — hides buyer private data."""

    my_items = serializers.SerializerMethodField()

    buyer_display = serializers.SerializerMethodField()

    class Meta:

        model = Order

        fields = (

            'id', 'status', 'total_amount', 'delivery_fee',

            'my_items', 'buyer_display', 'created_at', 'updated_at',

        )

    def get_my_items(self, obj):

        # Filtering in Python off the prefetched obj.items.all() cache -

        # obj.items.filter(...) would build a new queryset that bypasses the

        # view's prefetch_related('items__product'), re-querying once per

        # order row in a seller's sales list.

        seller = self.context['request'].user

        my_items = [item for item in obj.items.all() if item.product.seller_id == seller.id]

        return SellerOrderItemSerializer(my_items, many=True, context=self.context).data

    def get_buyer_display(self, obj):

        # We expose the shipping address to the seller so they can fulfill the order,

        # but we strictly DO NOT expose email, user ID, or other private profile data.

        return {

            "name": obj.student.first_name or "Buyer",

            "shipping_address": obj.shipping_address

        }

# ---------------------------------------------------------------------------

# Marketplace Settings

# ---------------------------------------------------------------------------

class MarketplaceSettingsSerializer(serializers.ModelSerializer):

    class Meta:

        model = MarketplaceSettings

        fields = '__all__'

        read_only_fields = ('updated_at',)

class MarketplacePricingPolicySerializer(serializers.ModelSerializer):

    """

    Read-only, student-facing subset of MarketplaceSettings - just the two

    fields a seller needs to price a used-book listing honestly: the real

    configured commission rate and the real 65%-style price cap. Deliberately

    excludes admin-only settings (allow_student_listings, minimum_payout_amount,

    etc.) that AdminMarketplaceSettingsView exposes.

    """

    class Meta:

        model = MarketplaceSettings

        fields = ('platform_commission_percentage', 'max_used_book_price_percent')

# ---------------------------------------------------------------------------

# Listing Report

# ---------------------------------------------------------------------------

class MarketplaceListingReportSerializer(serializers.ModelSerializer):

    reason_display = serializers.CharField(source='get_reason_display', read_only=True)

    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:

        model = MarketplaceListingReport

        fields = '__all__'

        read_only_fields = (

            'reporter', 'status', 'admin_response', 'created_at', 'updated_at',

            'resolved_at', 'resolved_by',

        )

# ---------------------------------------------------------------------------

# Trust & Safety

# ---------------------------------------------------------------------------

class ReviewSerializer(serializers.ModelSerializer):

    buyer_name = serializers.CharField(source='buyer.first_name', read_only=True)

    class Meta:

        model = Review

        fields = '__all__'

        read_only_fields = ('buyer', 'seller', 'product', 'status', 'created_at', 'updated_at')

class DisputeEvidenceSerializer(serializers.ModelSerializer):

    class Meta:

        model = DisputeEvidence

        fields = '__all__'

        read_only_fields = ('uploaded_by', 'created_at')

class DisputeSerializer(serializers.ModelSerializer):

    evidence = DisputeEvidenceSerializer(many=True, read_only=True)

    product_title = serializers.CharField(source='order_item.product.title', read_only=True)

    reason_display = serializers.CharField(source='get_reason_display', read_only=True)

    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:

        model = Dispute

        fields = '__all__'

        read_only_fields = (

            'buyer', 'seller', 'status', 'resolution', 'admin_notes', 

            'resolved_by', 'resolved_at', 'created_at', 'updated_at'

        )

# ---------------------------------------------------------------------------

# Payouts

# ---------------------------------------------------------------------------

class PayoutAccountSerializer(serializers.ModelSerializer):

    method_display = serializers.CharField(source='get_method_display', read_only=True)

    class Meta:

        model = PayoutAccount

        fields = '__all__'

        read_only_fields = ('seller', 'is_verified', 'created_at', 'updated_at')

class SellerPayoutSerializer(serializers.ModelSerializer):

    payout_account_details = PayoutAccountSerializer(source='payout_account', read_only=True)

    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:

        model = SellerPayout

        fields = '__all__'

        read_only_fields = (

            'seller', 'status', 'admin_note', 'rejection_reason', 

            'transaction_reference', 'processed_by', 'processed_at', 

            'created_at', 'updated_at'

        )

class AdminSellerPayoutSerializer(SellerPayoutSerializer):

    seller_name = serializers.CharField(source='seller.get_full_name', read_only=True)

    processed_by_name = serializers.CharField(source='processed_by.get_full_name', read_only=True)

class SellerBalanceSerializer(serializers.Serializer):

    total_earnings = serializers.DecimalField(max_digits=10, decimal_places=2)

    pending_payouts = serializers.DecimalField(max_digits=10, decimal_places=2)

    paid_out = serializers.DecimalField(max_digits=10, decimal_places=2)

    available_balance = serializers.DecimalField(max_digits=10, decimal_places=2)

    minimum_payout_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


# ---------------------------------------------------------------------------
# Nepal Can Move (NCM) Admin Configuration & Courier Serializers
# ---------------------------------------------------------------------------

class NCMConfigurationSerializer(serializers.ModelSerializer):
    """
    Serializer for NCM integration configuration.
    Strictly prevents exposing sensitive API tokens or secrets in responses.
    """
    masked_token = serializers.CharField(source='get_masked_token', read_only=True)
    token_source = serializers.CharField(source='get_token_source', read_only=True)
    effective_base_url = serializers.CharField(source='get_effective_base_url', read_only=True)
    has_token = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    # Allow setting a new token without ever returning it back in GET
    new_api_token = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Provide a new API token to override environment variable. Will be stored securely."
    )

    class Meta:
        model = NCMConfiguration
        fields = (
            'id',
            'is_enabled',
            'environment',
            'custom_base_url',
            'effective_base_url',
            'masked_token',
            'token_source',
            'has_token',
            'new_api_token',
            'default_origin_branch',
            'live_rates_enabled',
            'fallback_rules_enabled',
            'auto_sync_enabled',
            'webhook_enabled',
            'webhook_registered',
            'connection_status',
            'last_connection_tested_at',
            'last_connection_latency_ms',
            'last_connection_error',
            'last_sync_at',
            'last_sync_status',
            'branch_sync_source',
            'last_branch_sync_at',
            'branch_record_count',
            'last_webhook_received_at',
            'last_webhook_event',
            'last_webhook_error',
            'updated_at',
            'updated_by_name',
        )
        read_only_fields = (
            'id',
            'effective_base_url',
            'masked_token',
            'token_source',
            'has_token',
            'connection_status',
            'last_connection_tested_at',
            'last_connection_latency_ms',
            'last_connection_error',
            'last_sync_at',
            'last_sync_status',
            'branch_sync_source',
            'last_branch_sync_at',
            'branch_record_count',
            'last_webhook_received_at',
            'last_webhook_event',
            'last_webhook_error',
            'updated_at',
            'updated_by_name',
        )

    def get_has_token(self, obj) -> bool:
        return bool(obj.get_effective_token())

    def get_updated_by_name(self, obj) -> str:
        if obj.updated_by:
            return obj.updated_by.get_full_name() or obj.updated_by.username
        return "System"

    def update(self, instance, validated_data):
        new_token = validated_data.pop('new_api_token', None)
        request = self.context.get('request')
        clear_db_token = False
        if request and hasattr(request, 'data'):
            clear_db_token = request.data.get('clear_database_token', False)

        if clear_db_token or (new_token is not None and new_token == ''):
            instance.custom_api_token = ''
        elif new_token:
            from .models import clean_ncm_token
            clean_token = clean_ncm_token(new_token)
            instance.custom_api_token = clean_token

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            instance.updated_by = request.user

        instance.save()
        return instance


class NCMWebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = NCMWebhookEvent
        fields = '__all__'


class CourierSyncLogSerializer(serializers.ModelSerializer):
    synced_by_username = serializers.CharField(source='synced_by.username', read_only=True)

    class Meta:
        model = CourierSyncLog
        fields = '__all__'


class CODRemittanceSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    courier_tracking_id = serializers.SerializerMethodField()
    courier_status = serializers.SerializerMethodField()
    order_status = serializers.CharField(source='order.status', read_only=True)
    order_payment_status = serializers.CharField(source='order.payment_status', read_only=True)
    order_total = serializers.DecimalField(source='order.final_total', max_digits=10, decimal_places=2, read_only=True)
    advance_paid = serializers.DecimalField(source='order.cod_advance_paid', max_digits=10, decimal_places=2, read_only=True)
    remaining_balance = serializers.DecimalField(source='order.cod_remaining_balance', max_digits=10, decimal_places=2, read_only=True)
    verified_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CODRemittance
        fields = (
            'id',
            'order_id',
            'customer_name',
            'customer_phone',
            'courier_tracking_id',
            'courier_status',
            'order_status',
            'order_payment_status',
            'order_total',
            'advance_paid',
            'remaining_balance',
            'expected_amount',
            'courier_reported_amount',
            'remitted_amount',
            'status',
            'reference_number',
            'notes',
            'discrepancy_reason',
            'verified_at',
            'verified_by_name',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'order_id',
            'customer_name',
            'customer_phone',
            'courier_tracking_id',
            'courier_status',
            'order_status',
            'order_payment_status',
            'order_total',
            'advance_paid',
            'remaining_balance',
            'verified_at',
            'verified_by_name',
            'created_at',
            'updated_at',
        )

    def get_customer_name(self, obj) -> str:
        order = obj.order
        snapshot = order.shipping_address_snapshot or {}
        return snapshot.get('full_name') or order.student.get_full_name() or order.student.username

    def get_customer_phone(self, obj) -> str:
        order = obj.order
        snapshot = order.shipping_address_snapshot or {}
        return snapshot.get('phone_number') or order.contact_number or ""

    def get_courier_tracking_id(self, obj) -> str:
        if obj.courier_shipment:
            return obj.courier_shipment.tracking_id or obj.courier_shipment.ncm_order_id
        if hasattr(obj.order, 'courier_shipment') and obj.order.courier_shipment:
            return obj.order.courier_shipment.tracking_id or obj.order.courier_shipment.ncm_order_id
        return ""

    def get_courier_status(self, obj) -> str:
        if obj.courier_shipment:
            return obj.courier_shipment.courier_status
        if hasattr(obj.order, 'courier_shipment') and obj.order.courier_shipment:
            return obj.order.courier_shipment.courier_status
        return "Not Dispatched"

    def get_verified_by_name(self, obj) -> str:
        if obj.verified_by:
            return obj.verified_by.get_full_name() or obj.verified_by.username
        return ""


class NCMBranchCoordinateAuditLogSerializer(serializers.ModelSerializer):
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = NCMBranchCoordinateAuditLog
        fields = (
            'id',
            'branch',
            'changed_by',
            'changed_by_username',
            'previous_latitude',
            'previous_longitude',
            'new_latitude',
            'new_longitude',
            'previous_source',
            'new_source',
            'reason',
            'created_at',
        )
        read_only_fields = fields


class NCMBranchRecordSerializer(serializers.ModelSerializer):
    verified_by_username = serializers.CharField(source='verified_by.username', read_only=True)
    coordinate_logs = NCMBranchCoordinateAuditLogSerializer(many=True, read_only=True)
    areas_covered_list = serializers.SerializerMethodField()

    class Meta:
        model = NCMBranchRecord
        fields = (
            'id',
            'code',
            'name',
            'district_name',
            'province_name',
            'municipality',
            'address',
            'contact_number',
            'areas_covered',
            'areas_covered_list',
            'latitude',
            'longitude',
            'coordinate_source',
            'is_coordinate_verified',
            'coordinate_verified_at',
            'verified_by',
            'verified_by_username',
            'is_active',
            'is_serviceable',
            'serviceability_notes',
            'last_synced_at',
            'coordinate_logs',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'code',
            'created_at',
            'updated_at',
            'coordinate_verified_at',
            'verified_by',
            'verified_by_username',
            'last_synced_at',
        )

    def get_areas_covered_list(self, obj) -> list:
        if not obj.areas_covered:
            return []
        return [a.strip() for a in obj.areas_covered.replace('\n', ',').split(',') if a.strip()]



