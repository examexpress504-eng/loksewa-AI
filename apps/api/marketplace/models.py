from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
# pyrefly: ignore [missing-import]
from django.db import models, transaction
# pyrefly: ignore [missing-import]
from django.utils import timezone
# pyrefly: ignore [missing-import]
from django.core.validators import MinValueValidator, MaxValueValidator
from core.models import User
from exams.models import Exam
from core.upload_validators import validate_image_size_5mb, validate_image_extension


class Product(models.Model):
    PRODUCT_TYPES = (
        ('NEW_BOOK', 'New Book'),
        ('USED_BOOK', 'Used Book'),
        ('REFERENCE_BOOK', 'Reference Book'),
        ('GUIDE_BOOK', 'Guide Book'),
        ('GENERAL_KNOWLEDGE', 'General Knowledge'),
        ('CONSTITUTION_LAW', 'Constitution / Law'),
        ('CURRENT_AFFAIRS', 'Current Affairs'),
        ('STATIONERY', 'Stationery'),
    )

    CONDITION_CHOICES = (
        ('NEW', 'New'),
        ('LIKE_NEW', 'Like New'),
        ('VERY_GOOD', 'Very Good'),
        ('GOOD', 'Good'),
        ('FAIR', 'Fair'),
        ('ACCEPTABLE', 'Acceptable'),
    )

    LISTING_STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PENDING_REVIEW', 'Pending Review'),
        ('ACTIVE', 'Active'),
        ('REJECTED', 'Rejected'),
        ('SOLD', 'Sold'),
        ('SUSPENDED', 'Suspended'),
        ('ARCHIVED', 'Archived'),
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    features = models.JSONField(default=list, blank=True, help_text="List of features included")
    category = models.CharField(max_length=50, choices=PRODUCT_TYPES)

    # Physical / Used Book fields
    seller = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marketplace_listings'
    )
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, null=True, blank=True)
    # Detailed physical condition notes (S2S used books)
    condition_details = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Structured physical condition info. Keys: highlighting (bool), "
            "writing_notes (bool), page_damage (bool), cover_condition (str), "
            "missing_pages (bool), water_damage (bool), binding_condition (str), extra_notes (str)"
        )
    )
    stock = models.IntegerField(default=1)
    listing_status = models.CharField(
        max_length=20, choices=LISTING_STATUS_CHOICES, default='PENDING_REVIEW'
    )
    negotiable = models.BooleanField(default=False)
    location = models.CharField(max_length=255, blank=True)
    author = models.CharField(max_length=255, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    isbn = models.CharField(max_length=20, blank=True)
    edition = models.CharField(max_length=50, blank=True)
    publication_year = models.CharField(max_length=4, blank=True)
    published_date = models.CharField(max_length=100, blank=True, help_text='e.g. 2081 B.S. or 2024-05-01')
    total_pages = models.PositiveIntegerField(null=True, blank=True, help_text='Total number of pages in the book')
    brand = models.CharField(max_length=255, blank=True)

    target_exam = models.ForeignKey(
        Exam, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marketplace_products'
    )
    target_position = models.CharField(max_length=255, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Original price printed on the physical book, distinct from `price`
    # (what the seller is actually asking). Required at the SellerListingSerializer
    # level for student-to-student listings, which enforce
    # price <= marked_price * MarketplaceSettings.max_used_book_price_percent.
    # Nullable here because non-seller (platform) products predate this field
    # and don't carry a printed MRP concept the same way.
    marked_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    delivery_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Standard delivery / shipping charge set by administrator. 0 = Free delivery."
    )

    cover_image = models.ImageField(
        upload_to='marketplace/covers/', null=True, blank=True,
        validators=[validate_image_size_5mb, validate_image_extension],
        max_length=500,  # Google Drive proxy URLs exceed the default max_length=100
    )

    is_published = models.BooleanField(default=False)

    # Admin → seller communication on rejection
    rejection_reason = models.TextField(
        blank=True,
        help_text="Admin-written reason shown to the seller when a listing is rejected."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    @property
    def final_price(self):
        return self.discount_price if self.discount_price is not None else self.price

    @property
    def is_seller_listing(self):
        """True when this product was listed by a student seller (not platform stock)."""
        return self.seller is not None

    def save(self, *args, **kwargs):
        # Keep is_published and listing_status consistent
        if self.pk:
            old = Product.objects.filter(pk=self.pk).values('is_published', 'listing_status').first()
            if old:
                if not old['is_published'] and self.is_published:
                    if self.listing_status in ('PENDING_REVIEW', 'DRAFT', ''):
                        self.listing_status = 'ACTIVE'
                elif old['is_published'] and not self.is_published:
                    if self.listing_status == 'ACTIVE':
                        self.listing_status = 'DRAFT'
                elif self.is_published and self.listing_status in ('PENDING_REVIEW', 'DRAFT', ''):
                    self.listing_status = 'ACTIVE'
        else:
            if self.is_published:
                if self.listing_status in ('PENDING_REVIEW', 'DRAFT', ''):
                    self.listing_status = 'ACTIVE'
            else:
                if not self.seller and self.listing_status == 'PENDING_REVIEW':
                    self.listing_status = 'DRAFT'

        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = list(set(kwargs['update_fields']) | {'is_published', 'listing_status'})

        super().save(*args, **kwargs)


class PaymentMethod(models.Model):
    METHOD_CHOICES = (
        ('ESEWA', 'eSewa'),
        ('KHALTI', 'Khalti'),
        ('BANK', 'Bank Transfer'),
    )

    method_type = models.CharField(max_length=20, choices=METHOD_CHOICES, unique=True)
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=255)

    # Specific to bank
    bank_name = models.CharField(max_length=255, blank=True)
    branch = models.CharField(max_length=255, blank=True)

    qr_image = models.ImageField(
        upload_to='marketplace/payment_qrs/', null=True, blank=True,
        validators=[validate_image_size_5mb, validate_image_extension],
        max_length=500,  # Google Drive proxy URLs exceed the default max_length=100
    )
    instructions = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name


class PaymentSubmission(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_submissions')
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_submissions'
    )
    order = models.ForeignKey(
        'Order', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_submissions'
    )
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name='submissions'
    )

    transaction_id = models.CharField(max_length=255, unique=True)
    expected_amount = models.DecimalField(max_digits=10, decimal_places=2)
    submitted_amount = models.DecimalField(max_digits=10, decimal_places=2)

    screenshot = models.ImageField(
        upload_to='marketplace/payment_proofs/',
        validators=[validate_image_size_5mb, validate_image_extension],
        max_length=500,  # Google Drive proxy URLs exceed the default max_length=100
    )
    note = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    rejection_reason = models.TextField(blank=True)
    is_cod_advance = models.BooleanField(default=False, help_text="True if this submission is for a 15% COD advance payment.")
    attempt_number = models.PositiveIntegerField(default=1, help_text="Sequence number for retry attempts on this order.")

    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_payments'
    )

    def save(self, *args, **kwargs):
        if not self.student_id and self.order_id and self.order:
            self.student = self.order.student
        super().save(*args, **kwargs)

    def __str__(self):
        ref = self.product.title if self.product else f"Order #{self.order_id}"
        return f"{self.student.username} - {ref} - {self.status}"


class Purchase(models.Model):
    STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('REVOKED', 'Revoked'),
    )

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchases')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchases')
    payment_submission = models.OneToOneField(
        PaymentSubmission, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase'
    )

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'product')

    def __str__(self):
        return f"{self.student.username} bought {self.product.title}"


class ProductImage(models.Model):
    IMAGE_LABEL_CHOICES = (
        ('front_cover', 'Front Cover'),
        ('back_cover', 'Back Cover'),
        ('spine', 'Spine'),
        ('inside_pages', 'Inside Pages'),
        ('damage', 'Visible Damage'),
        ('other', 'Other'),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(
        upload_to='marketplace/product_images/',
        validators=[validate_image_size_5mb, validate_image_extension],
        max_length=500,  # Google Drive proxy URLs exceed the default max_length=100
    )
    label = models.CharField(
        max_length=20, choices=IMAGE_LABEL_CHOICES, default='other', blank=True
    )
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_label_display()} for {self.product.title}"


class DeliveryAddress(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='delivery_addresses')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    province = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    municipality = models.CharField(max_length=100)
    ward_number = models.CharField(max_length=10)
    tole_area = models.CharField(max_length=255)
    street_landmark = models.CharField(max_length=255, blank=True)
    delivery_note = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} - {self.district}, {self.province}"


class Cart(models.Model):
    student = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.student.username}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.quantity} x {self.product.title} in {self.cart.student.username}'s cart"


class Order(models.Model):
    STATUS_CHOICES = (
        ('PENDING_PAYMENT', 'Pending Payment'),
        ('PAYMENT_SUBMITTED', 'Payment Submitted'),
        ('PAYMENT_VERIFICATION', 'Payment Verification'),
        ('CONFIRMED', 'Confirmed'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('OUT_FOR_DELIVERY', 'Out for Delivery'),
        ('DELIVERED', 'Delivered'),
        ('ON_HOLD', 'On Hold'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
    )

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='marketplace_orders')
    PAYMENT_MODE_CHOICES = (
        ('PREPAID', 'Full Online Payment'),
        ('COD', 'Cash on Delivery (15% Advance)'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('UNPAID', 'Unpaid'),
        ('PARTIALLY_PAID', 'Partially Paid (COD Advance Verified)'),
        ('PAID', 'Fully Paid'),
        ('REFUNDED', 'Refunded'),
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING_PAYMENT')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    payment_method_type = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='PREPAID')
    is_cod = models.BooleanField(default=False)
    cod_advance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=15.00)
    cod_advance_required = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    cod_advance_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    cod_remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # NCM Courier Automatic Dispatch tracking fields (Phase 13)
    NCM_DISPATCH_STATUS_CHOICES = (
        ('NOT_REQUESTED', 'Not Requested'),
        ('QUEUED', 'Queued for Dispatch'),
        ('CREATING', 'Creating Shipment in NCM'),
        ('CREATED', 'Created in NCM'),
        ('FAILED', 'Dispatch Failed'),
        ('MANUAL_REVIEW_REQUIRED', 'Manual Review Required'),
    )

    ncm_dispatch_status = models.CharField(
        max_length=30,
        choices=NCM_DISPATCH_STATUS_CHOICES,
        default='NOT_REQUESTED',
        db_index=True,
        help_text="Current state of automatic or manual NCM courier dispatch.",
    )
    ncm_dispatch_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of attempts made to dispatch to NCM.",
    )
    ncm_dispatch_last_error = models.TextField(
        blank=True,
        help_text="Last error encountered during NCM dispatch.",
    )
    ncm_dispatch_next_retry = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the next automated retry should run.",
    )
    ncm_dispatch_last_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent dispatch attempt.",
    )

    # Store a snapshot of the shipping address as text and structured JSON
    shipping_address = models.TextField(blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    shipping_address_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Immutable snapshot of delivery address at the time the order was placed."
    )

    delivery_address_ref = models.ForeignKey(
        DeliveryAddress, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='orders'
    )

    # Hold / pause fields
    hold_reason = models.TextField(
        blank=True,
        help_text="Customer-supplied reason for placing the order on hold.",
    )
    held_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when the order was last put on hold.",
    )
    # Audit flag: set to True only when admin explicitly records advance forfeiture.
    # Never auto-set by customer hold/cancel flows.
    advance_forfeited = models.BooleanField(
        default=False,
        help_text=(
            "Set True only by explicit admin action when the 15% COD advance "
            "is officially forfeited. Never set automatically."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def final_total(self):
        return (self.total_amount + self.delivery_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def payment_mode(self):
        return self.payment_method_type

    @payment_mode.setter
    def payment_mode(self, value):
        self.payment_method_type = value

    def calculate_cod_amounts(self):
        """Authoritative calculation of 15% advance and remaining 85% balance."""
        tot = self.final_total
        if self.is_cod:
            self.cod_advance_required = (tot * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            advance_paid = Decimal(str(self.cod_advance_paid or '0.00'))
            if advance_paid > 0:
                self.cod_remaining_balance = max(Decimal('0.00'), (tot - advance_paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            else:
                self.cod_remaining_balance = max(Decimal('0.00'), (tot - self.cod_advance_required).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        else:
            self.cod_advance_required = Decimal('0.00')
            self.cod_remaining_balance = Decimal('0.00')

    def __str__(self):
        return f"Order #{self.id} by {self.student.username} - {self.status}"


class OrderItem(models.Model):
    FULFILLMENT_CHOICES = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    )

    PAYOUT_CHOICES = (
        ('PENDING', 'Pending'),
        ('ON_HOLD', 'On Hold'),
        ('ELIGIBLE', 'Eligible'),
        ('PROCESSING', 'Processing'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    )

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at the time of purchase")

    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    seller_earning = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    fulfillment_status = models.CharField(max_length=20, choices=FULFILLMENT_CHOICES, default='PENDING')
    payout_status = models.CharField(max_length=20, choices=PAYOUT_CHOICES, default='PENDING')
    
    snapshot_product_name = models.CharField(max_length=255, blank=True)
    snapshot_seller_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.quantity} x {self.product.title} (Order #{self.order.id})"


class DeliveryFeeRule(models.Model):
    name = models.CharField(max_length=255, help_text="E.g., Global Default, Kathmandu Valley")
    province = models.CharField(max_length=100, blank=True, help_text="Leave blank for global rule")
    district = models.CharField(max_length=100, blank=True, help_text="Leave blank to apply to entire province")
    municipality = models.CharField(max_length=100, blank=True, help_text="Leave blank to apply to entire district")

    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0, help_text="Higher priority rules override lower ones if both match")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f"{self.name} - Rs. {self.fee}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    previous_status = models.CharField(max_length=50, blank=True)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.order.id} status changed to {self.new_status}"


class CourierShipment(models.Model):
    """
    Dedicated model for third-party courier dispatches and tracking.
    Separates external courier status and lifecycle from internal Loksewa order statuses.
    """
    PROVIDER_CHOICES = (
        ('NCM', 'Nepal Can Move'),
    )

    STATUS_MAPPING = {
        'order created': 'PROCESSING',
        'order accepted': 'PROCESSING',
        'accepted': 'PROCESSING',
        'processing': 'PROCESSING',
        'pickup pending': 'PROCESSING',
        'pickup complete': 'SHIPPED',
        'picked up': 'SHIPPED',
        'in transit': 'SHIPPED',
        'dispatched': 'SHIPPED',
        'arrived at hub': 'SHIPPED',
        'at hub': 'SHIPPED',
        'out for delivery': 'OUT_FOR_DELIVERY',
        'delivered': 'DELIVERED',
        'delivery failed': 'ON_HOLD',
        'returned': 'ON_HOLD',
        'return': 'ON_HOLD',
        'cancelled': 'CANCELLED',
        'canceled': 'CANCELLED',
    }

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='courier_shipment',
        help_text="The marketplace order associated with this shipment."
    )
    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default='NCM'
    )
    ncm_order_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="External courier order identifier returned by provider."
    )
    tracking_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Customer-facing courier tracking number or code."
    )
    vref_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor reference ID (e.g. Loksewa order reference)."
    )
    origin_branch = models.CharField(
        max_length=100,
        default="Kathmandu",
        help_text="Origin merchant hub where package is dispatched from."
    )
    destination_branch = models.CharField(
        max_length=100,
        help_text="Destination courier hub handling local delivery."
    )
    delivery_type = models.CharField(
        max_length=50,
        default="Door2Door"
    )
    package_description = models.CharField(
        max_length=255,
        blank=True
    )
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text="Package weight in kg."
    )
    quoted_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Quoted delivery charge from rate calculation."
    )
    actual_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Actual delivery charge invoiced by courier provider."
    )
    cod_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Amount courier must collect on delivery (order.cod_remaining_balance for COD, 0 for Prepaid)."
    )
    courier_status = models.CharField(
        max_length=100,
        default="Order Created",
        help_text="Raw status string directly from courier provider."
    )
    status_history = models.JSONField(
        default=list,
        blank=True,
        help_text="Audit log of provider milestone events and timestamps."
    )
    raw_response = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw provider response payload from shipment creation."
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last timestamp when tracking status was synchronized."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', 'ncm_order_id']),
            models.Index(fields=['tracking_id']),
        ]

    def __str__(self):
        return f"{self.provider} Shipment #{self.ncm_order_id} for Order #{self.order_id}"

    def get_mapped_order_status(self):
        """Returns the internal order status corresponding to the provider status, or None."""
        if not self.courier_status:
            return None
        cleaned = self.courier_status.strip().lower()
        for key, val in self.STATUS_MAPPING.items():
            if key in cleaned:
                return val
        return None

    def apply_status_update(self, new_courier_status=None, history_list=None, tracking_id=None, changed_by=None, source="courier_sync"):
        """
        Updates courier status, tracking history, and orchestrates internal order state transitions.
        Strictly preserves the 15% advance / 85% COD payment rule:
        Delivered status does NOT mark an unverified COD order as PAID (requires admin remittance verification).
        """
        with transaction.atomic():
            shipment = CourierShipment.objects.select_for_update().get(pk=self.pk)
            order = shipment.order

            if new_courier_status:
                shipment.courier_status = new_courier_status
            if tracking_id:
                shipment.tracking_id = tracking_id
            if history_list is not None:
                shipment.status_history = history_list
            shipment.last_synced_at = timezone.now()
            shipment.save(update_fields=['courier_status', 'tracking_id', 'status_history', 'last_synced_at', 'updated_at'])

            mapped_status = shipment.get_mapped_order_status()
            status_changed = False
            if mapped_status and mapped_status != order.status:
                valid_milestone_progression = {
                    'CONFIRMED': ['PROCESSING', 'SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED'],
                    'PROCESSING': ['SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED'],
                    'SHIPPED': ['OUT_FOR_DELIVERY', 'DELIVERED'],
                    'OUT_FOR_DELIVERY': ['DELIVERED'],
                }
                if mapped_status in valid_milestone_progression.get(order.status, []):
                    old_st = order.status
                    order.status = mapped_status
                    order.save(update_fields=['status', 'updated_at'])

                    OrderStatusHistory.objects.create(
                        order=order,
                        previous_status=old_st,
                        new_status=mapped_status,
                        changed_by=changed_by,
                        note=f"Status updated via {source}: {shipment.courier_status}",
                    )
                    order.items.exclude(fulfillment_status=mapped_status).update(fulfillment_status=mapped_status)

                    if mapped_status == 'DELIVERED':
                        order.items.filter(product__seller__isnull=False, payout_status='PENDING').update(payout_status='ELIGIBLE')
                        # Strict rule: For COD orders, payment_status remains PARTIALLY_PAID until admin confirms remittance!
                    status_changed = True

            self.refresh_from_db()
            return status_changed


# ---------------------------------------------------------------------------
# S2S Marketplace Extensions
# ---------------------------------------------------------------------------

class MarketplaceSettings(models.Model):
    """Singleton table for platform-wide marketplace configuration."""

    platform_commission_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=5.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Platform fee deducted from seller earnings (%). 0 = no fee."
    )
    max_used_book_price_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=65.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=(
            "A student-listed used book's asking price (Product.price) cannot "
            "exceed this percentage of its marked/printed price (Product.marked_price). "
            "Enforced in SellerListingSerializer."
        )
    )
    max_listing_images = models.PositiveIntegerField(
        default=6,
        help_text="Maximum number of images a seller can upload per listing."
    )
    allow_student_listings = models.BooleanField(
        default=True,
        help_text="When off, students cannot create new listings (existing ones unaffected)."
    )
    minimum_payout_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=500.00,
        help_text="Minimum available balance required to request a payout."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Marketplace Settings"
        verbose_name_plural = "Marketplace Settings"

    def __str__(self):
        return "Marketplace Settings"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MarketplaceListingReport(models.Model):
    """A student's report/flag against a published listing."""

    REASON_CHOICES = (
        ('fake_book', 'Fake or Incorrect Book'),
        ('wrong_condition', 'Condition Does Not Match Description'),
        ('misleading_images', 'Misleading Images'),
        ('wrong_price', 'Wrong or Manipulated Price'),
        ('spam', 'Spam or Duplicate Listing'),
        ('prohibited', 'Prohibited Item'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('REVIEWED', 'Reviewed'),
        ('DISMISSED', 'Dismissed'),
    )

    listing = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='reports'
    )
    reporter = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='listing_reports'
    )
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    admin_response = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_reports')

    class Meta:
        # One reporter can only submit one report per listing
        unique_together = ('listing', 'reporter')
        ordering = ['-created_at']

    def __str__(self):
        return f"Report on '{self.listing.title}' by {self.reporter.username} — {self.status}"


class Review(models.Model):
    STATUS_CHOICES = (
        ('PUBLISHED', 'Published'),
        ('HIDDEN', 'Hidden'),
        ('FLAGGED', 'Flagged'),
    )

    order_item = models.OneToOneField(OrderItem, on_delete=models.CASCADE, related_name='review')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_given')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_received')
    
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    review_text = models.TextField(blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PUBLISHED')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.rating} star by {self.buyer.username} for {self.product.title}"


class Dispute(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('UNDER_REVIEW', 'Under Review'),
        ('RESOLVED', 'Resolved'),
        ('REJECTED', 'Rejected'),
    )

    REASON_CHOICES = (
        ('not_arrived', 'Book never arrived'),
        ('different', 'Significantly different from description'),
        ('damaged', 'Damaged book'),
        ('missing_pages', 'Missing pages'),
        ('wrong_item', 'Wrong book received'),
        ('delivery_issue', 'Delivery problem'),
        ('other', 'Other'),
    )

    order_item = models.OneToOneField(OrderItem, on_delete=models.CASCADE, related_name='dispute')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='disputes_raised')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='disputes_received')
    
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    description = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    resolution = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_disputes')
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Dispute #{self.id} for OrderItem #{self.order_item.id}"


class DisputeEvidence(models.Model):
    dispute = models.ForeignKey(Dispute, on_delete=models.CASCADE, related_name='evidence')
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    image = models.ImageField(
        upload_to='marketplace/dispute_evidence/',
        validators=[validate_image_size_5mb, validate_image_extension],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Evidence for Dispute #{self.dispute.id}"


# ---------------------------------------------------------------------------
# S2S Payouts
# ---------------------------------------------------------------------------

class PayoutAccount(models.Model):
    METHOD_CHOICES = (
        ('ESEWA', 'eSewa'),
        ('KHALTI', 'Khalti'),
        ('BANK', 'Bank Transfer'),
    )

    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payout_accounts')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    account_name = models.CharField(max_length=255)
    account_identifier = models.CharField(max_length=255, help_text="eSewa ID, Khalti ID, or Bank Account Number")
    
    # Specific to bank
    bank_name = models.CharField(max_length=255, blank=True)
    branch = models.CharField(max_length=255, blank=True)

    is_verified = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_method_display()} - {self.account_identifier} ({self.seller.username})"


class SellerPayout(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('PROCESSING', 'Processing'),
        ('PAID', 'Paid'),
        ('REJECTED', 'Rejected'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    )

    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts')
    payout_account = models.ForeignKey(PayoutAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='payouts')
    requested_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    admin_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    transaction_reference = models.CharField(max_length=255, blank=True)
    
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_payouts')
    processed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payout #{self.id} for {self.seller.username} - {self.status}"


# ---------------------------------------------------------------------------
# Nepal Can Move (NCM) Admin Configuration & COD Remittance Management
# ---------------------------------------------------------------------------

def clean_ncm_token(token) -> str:
    """Sanitize NCM API token by stripping surrounding quotes, whitespace, and leading 'Token'/'Bearer' prefixes."""
    if not token:
        return ""
    clean = str(token).strip().strip("\"'").strip()
    if clean.lower().startswith("token "):
        clean = clean[6:].strip()
    elif clean.lower().startswith("bearer "):
        clean = clean[7:].strip()
    return clean.strip("\"'").strip()


class NCMConfiguration(models.Model):
    """
    Singleton configuration model for Nepal Can Move (NCM) courier integration.
    Allows administrators to configure integration toggles, default origin branch,
    live rates, fallback delivery rules, auto-sync, and connection diagnostics
    dynamically without redeploying.
    Deployment-level credentials default to Render environment variables.
    """
    ENVIRONMENT_CHOICES = (
        ('demo', 'Demo / Sandbox'),
        ('production', 'Production (Live)'),
    )

    is_enabled = models.BooleanField(
        default=True,
        help_text="Master toggle to enable or disable NCM courier integration."
    )
    environment = models.CharField(
        max_length=20,
        choices=ENVIRONMENT_CHOICES,
        default='demo',
        help_text="Active NCM API environment."
    )
    custom_base_url = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional custom API base URL override. If blank, standard demo/production URLs are used."
    )
    custom_api_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional API token override. If blank, settings.NCM_API_TOKEN is used."
    )
    default_origin_branch = models.CharField(
        max_length=100,
        default='Kathmandu',
        help_text="Default dispatch origin hub branch name (e.g. Kathmandu)."
    )
    live_rates_enabled = models.BooleanField(
        default=True,
        help_text="Enable real-time dynamic shipping rate calculation via NCM API."
    )
    fallback_rules_enabled = models.BooleanField(
        default=False,
        help_text="Enable fallback to local delivery fee rules if NCM API is temporarily unavailable."
    )
    auto_sync_enabled = models.BooleanField(
        default=True,
        help_text="Enable automated tracking status synchronization."
    )
    webhook_enabled = models.BooleanField(
        default=True,
        help_text="Allow incoming webhook status updates from NCM."
    )
    webhook_registered = models.BooleanField(
        default=False,
        help_text="Indicates whether the webhook URL is registered with NCM."
    )

    # Diagnostics and Health tracking
    connection_status = models.CharField(
        max_length=50,
        default='untested',
        help_text="Current connection health: connected, error, or untested."
    )
    last_connection_tested_at = models.DateTimeField(null=True, blank=True)
    last_connection_latency_ms = models.IntegerField(null=True, blank=True)
    last_connection_error = models.TextField(blank=True)

    # Sync and Webhook telemetry
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_webhook_received_at = models.DateTimeField(null=True, blank=True)
    last_webhook_event = models.CharField(max_length=100, blank=True)
    last_webhook_error = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ncm_config_updates'
    )

    class Meta:
        verbose_name = "Nepal Can Move Configuration"
        verbose_name_plural = "Nepal Can Move Configuration"

    def __str__(self):
        return f"NCM Configuration ({self.environment}) - {'Enabled' if self.is_enabled else 'Disabled'}"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_effective_base_url(self):
        if self.custom_base_url:
            url = self.custom_base_url.strip()
        elif getattr(settings, 'NCM_BASE_URL', ''):
            url = getattr(settings, 'NCM_BASE_URL', '').strip()
        elif self.environment == 'production':
            url = 'https://portal.nepalcanmove.com/api/'
        else:
            url = 'https://demo.nepalcanmove.com/api/'
        if not url.endswith('/'):
            url += '/'
        return url

    def get_effective_token(self):
        raw = self.custom_api_token or getattr(settings, 'NCM_API_TOKEN', '')
        return clean_ncm_token(raw)

    def get_masked_token(self):
        token = self.get_effective_token()
        if not token:
            return ''
        if len(token) <= 8:
            return '****'
        return f"{token[:4]}****{token[-4:]}"

    def get_token_source(self):
        if self.custom_api_token:
            return 'database'
        if getattr(settings, 'NCM_API_TOKEN', ''):
            return 'environment'
        return 'not_configured'


class NCMWebhookEvent(models.Model):
    """
    Audit log of webhook payloads received from Nepal Can Move.
    Provides diagnostic history and verification traces.
    """
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.CharField(max_length=50, blank=True)
    event_type = models.CharField(max_length=100, blank=True)
    ncm_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    tracking_id = models.CharField(max_length=100, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    is_success = models.BooleanField(default=True)
    status_code = models.IntegerField(default=200)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"Webhook {self.event_type} - {self.ncm_order_id} at {self.received_at}"


class CourierSyncLog(models.Model):
    """
    Audit log of courier tracking synchronization runs.
    """
    synced_at = models.DateTimeField(auto_now_add=True, db_index=True)
    synced_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    trigger_type = models.CharField(max_length=50, default='manual')  # manual, celery_beat, cron
    shipments_checked = models.PositiveIntegerField(default=0)
    shipments_updated = models.PositiveIntegerField(default=0)
    errors_count = models.PositiveIntegerField(default=0)
    error_details = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, default='SUCCESS')  # SUCCESS, PARTIAL, FAILED

    class Meta:
        ordering = ['-synced_at']

    def __str__(self):
        return f"Sync ({self.trigger_type}) at {self.synced_at} - {self.status}"


class CODRemittance(models.Model):
    """
    Financial remittance record for Cash on Delivery (COD) courier shipments.
    Ensures safe, verified settlement of the remaining 85% COD balance collected by NCM.

    STRICT BUSINESS & ACCOUNTING RULES:
    1. A delivered NCM shipment does NOT mark an order as PAID.
    2. An order is only settled when an authorized administrator verifies actual courier deposit.
    3. OneToOneField prevents duplicate remittance records per order.
    4. Settlement transitions order.payment_status to PAID and cod_remaining_balance to 0.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending Courier Remittance'),
        ('VERIFIED', 'Remittance Verified & Settled'),
        ('DISCREPANCY', 'Amount Discrepancy Flagged'),
        ('REJECTED', 'Remittance Rejected'),
    )

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='cod_remittance',
        help_text="Marketplace order for which COD was collected."
    )
    courier_shipment = models.ForeignKey(
        CourierShipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cod_remittances',
        help_text="Associated NCM courier shipment."
    )
    expected_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Expected COD amount to be collected (Order.cod_remaining_balance)."
    )
    courier_reported_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount courier claims to have collected."
    )
    remitted_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual net funds deposited/remitted to bank account."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        db_index=True
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Courier deposit slip / bank reference / statement voucher number."
    )
    notes = models.TextField(blank=True)
    discrepancy_reason = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_cod_remittances'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"COD Remittance for Order #{self.order_id} - {self.status} (NPR {self.expected_amount})"

    def verify_and_settle(self, verified_by, remitted_amount=None, reference_number='', notes=''):
        """
        Safely records courier remittance, verifies payment, and marks order as fully PAID.
        Prevents duplicate verification.
        """
        from rest_framework.exceptions import ValidationError as DRFValidationError
        with transaction.atomic():
            remittance = CODRemittance.objects.select_for_update().get(pk=self.pk)
            if remittance.status == 'VERIFIED':
                raise DRFValidationError("This COD remittance has already been verified and settled.")

            order = Order.objects.select_for_update().get(pk=remittance.order_id)
            if not order.is_cod:
                raise DRFValidationError("Order is not a Cash on Delivery (COD) order.")

            actual_remitted = Decimal(str(remitted_amount if remitted_amount is not None else remittance.expected_amount))
            if actual_remitted < 0:
                raise DRFValidationError("Remitted amount cannot be negative.")

            remittance.remitted_amount = actual_remitted
            remittance.reference_number = (reference_number or '').strip()
            remittance.notes = (notes or '').strip()
            remittance.status = 'VERIFIED'
            remittance.verified_by = verified_by
            remittance.verified_at = timezone.now()
            remittance.save()

            # Settle remaining COD balance on order
            old_payment_status = order.payment_status
            order.cod_remaining_balance = Decimal('0.00')
            order.payment_status = 'PAID'
            order.save(update_fields=['cod_remaining_balance', 'payment_status', 'updated_at'])

            OrderStatusHistory.objects.create(
                order=order,
                previous_status=order.status,
                new_status=order.status,
                changed_by=verified_by,
                note=f"COD Remittance verified (NPR {actual_remitted}, Ref: {remittance.reference_number or 'N/A'}). Payment status transitioned from {old_payment_status} to PAID.",
            )

            # Audit log
            try:
                from administration.models import AuditLog
                AuditLog.objects.create(
                    actor=verified_by,
                    action='VERIFY_COD_REMITTANCE',
                    entity_type='Order',
                    entity_id=str(order.id),
                    details={
                        'remittance_id': remittance.id,
                        'expected_amount': float(remittance.expected_amount),
                        'remitted_amount': float(actual_remitted),
                        'reference_number': remittance.reference_number,
                    }
                )
            except Exception:
                pass

            self.refresh_from_db()
            return remittance


class NCMBranchRecord(models.Model):
    """
    Persistent database representation of Nepal Can Move (NCM) branches.
    Enriched with geographic coordinates, coordinate verification provenance,
    local-level coverage metadata, and serviceability status.
    """
    COORDINATE_SOURCES = (
        ('API', 'NCM API Direct'),
        ('ADMIN_VERIFIED', 'Admin Verified'),
        ('GEOCODED', 'Geocoded Address / Place'),
        ('MUNICIPALITY_CENTROID', 'Municipality Centroid Fallback'),
        ('DISTRICT_CENTROID', 'District Centroid Fallback'),
        ('UNVERIFIED', 'Unverified / Unknown'),
    )

    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    district_name = models.CharField(max_length=100, blank=True, default='', db_index=True)
    province_name = models.CharField(max_length=100, blank=True, default='', db_index=True)
    municipality = models.CharField(max_length=150, blank=True, default='', db_index=True)
    address = models.TextField(blank=True, default='')
    contact_number = models.CharField(max_length=100, blank=True, default='')
    areas_covered = models.TextField(blank=True, default='', help_text="Comma-separated or newline-separated coverage list")
    
    # Geographic coordinates (WGS-84)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    coordinate_source = models.CharField(max_length=30, choices=COORDINATE_SOURCES, default='UNVERIFIED')
    is_coordinate_verified = models.BooleanField(default=False, db_index=True)
    coordinate_verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_ncm_branches'
    )

    # Operational status
    is_active = models.BooleanField(default=True, db_index=True)
    is_serviceable = models.BooleanField(default=True, help_text="Can deliveries be dispatched to this branch?")
    serviceability_notes = models.TextField(blank=True, default='')

    # Metadata & sync tracking
    raw_metadata = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['district_name', 'name']
        indexes = [
            models.Index(fields=['district_name', 'is_active']),
            models.Index(fields=['is_serviceable', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.district_name or 'Unknown District'}"

    @property
    def has_valid_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class NCMBranchCoordinateAuditLog(models.Model):
    """
    Audit log tracking modifications to NCM branch coordinates and verification status.
    """
    branch = models.ForeignKey(NCMBranchRecord, on_delete=models.CASCADE, related_name='coordinate_logs')
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    previous_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    previous_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    new_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    new_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    previous_source = models.CharField(max_length=50, blank=True, default='')
    new_source = models.CharField(max_length=50, blank=True, default='')
    reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Coordinate change for {self.branch.name} at {self.created_at}"


