import { apiClient } from "./client";
import { getProvinceForDistrict } from "@/lib/constants/nepal-districts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProductImage {
  id: number;
  product: number;
  image: string;
  label: string;
  label_display?: string;
  is_primary: boolean;
  created_at: string;
}

export interface SellerDetails {
  id: number;
  first_name: string;
  last_name?: string;
  full_name?: string;
  member_since: string | null;
  average_rating?: number;
  total_reviews?: number;
}

export interface Product {
  id: number;
  title: string;
  description: string;
  features: string[];
  category: string;
  category_display?: string;
  target_exam: number | null;
  target_position: string;
  price: string;
  discount_price: string | null;
  marked_price?: string | null;
  final_price: string;
  delivery_fee?: string;
  cover_image: string | null;
  is_published: boolean;
  is_seller_listing: boolean;

  // Physical/Seller fields
  condition?: string | null;
  condition_display?: string | null;
  condition_details?: {
    highlighting?: boolean;
    writing_notes?: boolean;
    page_damage?: boolean;
    cover_condition?: string;
    missing_pages?: boolean;
    water_damage?: boolean;
    binding_condition?: string;
    extra_notes?: string;
  };
  stock?: number;
  listing_status?: string;
  listing_status_display?: string;
  negotiable?: boolean;
  location?: string;
  author?: string;
  publisher?: string;
  isbn?: string;
  edition?: string;
  publication_year?: string;
  published_date?: string;
  total_pages?: number | null;
  brand?: string;
  seller?: number | null;
  seller_details?: SellerDetails | null;
  rejection_reason?: string;

  // Relations
  images?: ProductImage[];

  created_at: string;
  updated_at: string;
  average_rating?: number;
  total_reviews?: number;
}

export interface PaymentMethod {
  id: number;
  method_type: "ESEWA" | "KHALTI" | "BANK";
  display_name: string;
  is_active: boolean;
  account_name: string;
  account_number: string;
  bank_name: string;
  branch: string;
  qr_image: string | null;
  qr_image_direct?: string | null;
  instructions: string;
}

export interface PaymentSubmissionOrderItem {
  id: number;
  product_id?: number | null;
  title: string;
  quantity: number;
  price: string;
  total_price?: string;
  cover_image?: string | null;
  category?: string | null;
  condition?: string | null;
  seller_name?: string | null;
}

export interface PaymentSubmissionOrderDetails {
  id: number;
  total_amount: string;
  delivery_fee: string;
  final_total: string;
  is_cod: boolean;
  payment_method_type: string;
  cod_advance_required: string;
  cod_advance_paid: string;
  cod_remaining_balance: string;
  status: string;
  payment_status: string;
  shipping_address: string;
  shipping_address_snapshot: Record<string, any>;
  contact_number?: string;
  items: PaymentSubmissionOrderItem[];
}

export interface PaymentSubmission {
  id: number;
  student: number;
  student_details?: {
    id: number;
    username?: string;
    first_name?: string;
    last_name?: string;
    full_name?: string;
    email?: string;
    [key: string]: unknown;
  };
  product: number | null;
  product_id?: number | null;
  product_details?: Product | null;
  product_name?: string;
  order: number | null;
  payment_method: number;
  payment_method_details?: PaymentMethod;
  transaction_id: string;
  expected_amount: string;
  submitted_amount: string;
  screenshot: string;
  note: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  rejection_reason: string;
  is_cod_advance?: boolean;
  attempt_number?: number;
  order_details?: PaymentSubmissionOrderDetails | null;
  submitted_at: string;
  verified_at: string | null;
}

export interface Purchase {
  id: number;
  student: number;
  product: number;
  product_details?: Product;
  payment_submission: number;
  payment_submission_details?: PaymentSubmission;
  amount_paid: string;
  status: "ACTIVE" | "REVOKED";
  created_at: string;
  approved_at: string;
}

export interface CartItem {
  id: number;
  cart: number;
  product: number;
  product_details?: Product;
  quantity: number;
  created_at: string;
  updated_at: string;
}

export interface Cart {
  id: number;
  student: number;
  items: CartItem[];
  created_at: string;
  updated_at: string;
}

export interface OrderItem {
  id: number;
  order: number;
  product: number;
  product_details?: Product;
  quantity: number;
  price: string;
  commission_amount?: string;
  seller_earning?: string;
  fulfillment_status?: "PENDING" | "PROCESSING" | "SHIPPED" | "DELIVERED" | "CANCELLED";
  payout_status?: "PENDING" | "ELIGIBLE" | "PROCESSING" | "PAID" | "FAILED" | "CANCELLED";
  snapshot_product_name?: string;
  snapshot_seller_name?: string;
}

export interface DeliveryAddress {
  id: number;
  student: number;
  full_name: string;
  phone_number: string;
  province: string;
  district: string;
  municipality: string;
  ward_number: string;
  tole_area: string;
  street_landmark: string;
  delivery_note: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface OrderStatusHistory {
  id: number;
  order: number;
  previous_status: string;
  new_status: string;
  changed_by: number | null;
  changed_by_name: string;
  note: string;
  created_at: string;
}

export interface DeliveryFeeRule {
  id: number;
  name: string;
  province: string;
  district: string;
  municipality: string;
  fee: string;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface NCMBranch {
  id?: number;
  code: string;
  name: string;
  district_name: string;
  province_name: string;
  municipality?: string;
  address?: string;
  contact_number?: string;
  areas_covered: string[];
  areas_covered_list?: string[];
  match_type?: "municipality" | "district" | "nearby" | "regional" | null;
  match_label?: string;
  is_recommended?: boolean;
  approx_distance_km?: number | null;
  distance_km?: number | null;
  distance_label?: string;
  radius_zone?: "primary" | "extended" | "regional" | "far" | "unknown";
  coverage_type?: "local_level" | "district" | "cross_district_nearby" | "regional";
  coverage_label?: string;
  is_serviceable?: boolean;
  serviceability_status?: "VERIFIED_SERVICEABLE" | "UNSERVICEABLE";
  coordinate_source?: string;
  is_coordinate_verified?: boolean;
  coordinate_verified_at?: string | null;
  verified_by_username?: string;
  serviceability_notes?: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface NCMBranchesResponse {
  enabled: boolean;
  branches: NCMBranch[];
  suggested_branches: NCMBranch[];
  nearby_branches?: NCMBranch[];
  auto_selected: string | null;
  origin_branch: string;
  fallback_enabled: boolean;
  match_type?: "municipality" | "district" | "nearby" | "none";
  match_priority?: number;
  message?: string;
  search_municipality?: string;
  search_district?: string;
  search_province?: string;
  delivery_anchor?: {
    latitude?: number | null;
    longitude?: number | null;
    source?: string;
    municipality?: string;
    district?: string;
    province?: string;
  } | null;
  recommended_branch?: NCMBranch | null;
  error?: string;
}

export interface DeliveryFeeResponse {
  delivery_fee: number;
  fee_source?: "ncm" | "rule_fallback" | "ncm_error" | "requires_branch";
  destination_branch?: string;
  delivery_type?: string;
  fallback_applied?: boolean;
  fallback_reason?: string;
  detail?: string;
}

export interface CourierShipment {
  id: number;
  order: number;
  provider: string;
  ncm_order_id: string;
  tracking_id: string;
  vref_id: string;
  origin_branch: string;
  destination_branch: string;
  delivery_type: string;
  package_description: string;
  weight: string;
  quoted_charge: string;
  actual_charge: string;
  cod_charge: string;
  courier_status: string;
  status_history: Array<{
    status?: string;
    state?: string;
    timestamp?: string;
    time?: string;
    comments?: string;
    remarks?: string;
    location?: string;
    [key: string]: any;
  }>;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NCMConfiguration {
  id: number;
  is_enabled: boolean;
  environment: "demo" | "production";
  custom_base_url: string;
  effective_base_url: string;
  masked_token: string;
  token_source: "database" | "environment" | "not_configured";
  has_token: boolean;
  new_api_token?: string;
  default_origin_branch: string;
  live_rates_enabled: boolean;
  fallback_rules_enabled: boolean;
  auto_sync_enabled: boolean;
  webhook_enabled: boolean;
  webhook_registered: boolean;
  connection_status: "connected" | "error" | "untested";
  last_connection_tested_at: string | null;
  last_connection_latency_ms: number | null;
  last_connection_error: string;
  last_sync_at: string | null;
  last_sync_status: string;
  last_webhook_received_at: string | null;
  last_webhook_event: string;
  last_webhook_error: string;
  updated_at: string;
  updated_by_name: string;
  render_env_status?: {
    token_in_env: boolean;
    token_masked: string;
    webhook_secret_in_env: boolean;
    webhook_secret_status: string;
  };
  webhook_endpoint_url?: string;
  fallback_pricing_source?: string;
}

export interface NCMWebhookEvent {
  id: number;
  received_at: string;
  ip_address: string;
  event_type: string;
  ncm_order_id: string;
  tracking_id: string;
  payload: any;
  is_success: boolean;
  status_code: number;
  error_message: string;
}

export interface CourierSyncLog {
  id: number;
  synced_at: string;
  synced_by_username: string | null;
  trigger_type: string;
  shipments_checked: number;
  shipments_updated: number;
  errors_count: number;
  error_details: any[];
  status: "SUCCESS" | "PARTIAL" | "FAILED";
}

export interface CODRemittance {
  id: number;
  order_id: number;
  customer_name: string;
  customer_phone: string;
  courier_tracking_id: string;
  courier_status: string;
  order_status: string;
  order_payment_status: string;
  order_total: string;
  advance_paid: string;
  remaining_balance: string;
  expected_amount: string;
  courier_reported_amount: string | null;
  remitted_amount: string | null;
  status: "PENDING" | "VERIFIED" | "DISCREPANCY" | "REJECTED";
  reference_number: string;
  notes: string;
  discrepancy_reason: string;
  verified_at: string | null;
  verified_by_name: string;
  created_at: string;
  updated_at: string;
}

export interface CourierOverviewData {
  metrics: {
    total_shipments: number;
    pending_pickup: number;
    in_transit: number;
    out_for_delivery: number;
    delivered: number;
    returned: number;
    failed_sync_count: number;
    remittance_pending_count: number;
    remittance_pending_amount: number;
    remittance_verified_count: number;
    remittance_verified_amount: number;
    remittance_discrepancy_count: number;
  };
  configuration: Partial<NCMConfiguration>;
  scheduler: {
    render_cron_job_command: string;
    celery_worker_present: boolean;
    auto_sync_active: boolean;
    last_sync: CourierSyncLog | null;
  };
  recent_shipments: CourierShipment[];
}

export interface Order {
  id: number;
  student: number;
  status:
    | "PENDING_PAYMENT"
    | "PAYMENT_SUBMITTED"
    | "PAYMENT_VERIFICATION"
    | "CONFIRMED"
    | "PROCESSING"
    | "SHIPPED"
    | "OUT_FOR_DELIVERY"
    | "DELIVERED"
    | "ON_HOLD"
    | "CANCELLED"
    | "REFUNDED";
  hold_reason?: string;
  held_at?: string | null;
  advance_forfeited?: boolean;
  payment_status?: "UNPAID" | "PARTIALLY_PAID" | "PAID" | "REFUNDED";
  payment_method_type?: "PREPAID" | "COD";
  payment_mode?: "PREPAID" | "COD";
  is_cod?: boolean;
  cod_advance_rate?: string | number;
  cod_advance_required?: string;
  cod_advance_paid?: string;
  cod_remaining_balance?: string;
  total_amount: string;
  delivery_fee: string;
  final_total?: string;
  shipping_address: string;
  contact_number: string;
  shipping_address_snapshot?: Record<string, any>;
  delivery_address_ref?: number | null;
  delivery_address_details?: DeliveryAddress;
  items: OrderItem[];
  status_history?: OrderStatusHistory[];
  ncm_dispatch_status?:
    | "NOT_REQUESTED"
    | "QUEUED"
    | "CREATING"
    | "CREATED"
    | "FAILED"
    | "MANUAL_REVIEW_REQUIRED";
  ncm_dispatch_attempts?: number;
  ncm_dispatch_last_error?: string;
  ncm_dispatch_next_retry?: string | null;
  ncm_dispatch_last_attempt_at?: string | null;
  courier_shipment?: CourierShipment | null;
  latest_payment_submission?: {
    id: number;
    status: "PENDING" | "APPROVED" | "REJECTED";
    rejection_reason: string;
    transaction_id: string;
    expected_amount: string;
    submitted_amount: string;
    is_cod_advance: boolean;
    attempt_number: number;
    submitted_at: string | null;
    verified_at: string | null;
    payment_method_id: number;
    payment_method_name: string | null;
  } | null;
  can_retry_payment?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProfileAddressResponse {
  full_name: string;
  phone_number: string;
  province: string;
  district: string;
  municipality: string;
  ward_number: string;
  tole_area: string;
  street_landmark: string;
  delivery_note: string;
  missing_fields: string[];
  is_profile_complete: boolean;
}

/** Seller's view of an order (buyer identity is anonymized) */
export interface SellerSale {
  id: number;
  status: Order["status"];
  total_amount: string;
  delivery_fee: string;
  buyer_display: { name: string; shipping_address: string };
  my_items: {
    id: number;
    product: number;
    product_details: { id: number; title: string; cover_image: string | null };
    quantity: number;
    price: string;
    commission_amount: string;
    seller_earning: string;
    fulfillment_status: "PENDING" | "PROCESSING" | "SHIPPED" | "DELIVERED" | "CANCELLED";
    payout_status: "PENDING" | "ELIGIBLE" | "PROCESSING" | "PAID" | "FAILED" | "CANCELLED";
    snapshot_product_name: string;
  }[];
  created_at: string;
  updated_at: string;
}

export interface MarketplaceListingReport {
  id: number;
  listing: number;
  reporter: number;
  reason: string;
  reason_display?: string;
  description: string;
  status: "PENDING" | "REVIEWED" | "DISMISSED";
  status_display?: string;
  admin_response: string;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceSettings {
  id: number;
  platform_commission_percentage: string;
  max_used_book_price_percent: string;
  max_listing_images: number;
  allow_student_listings: boolean;
  updated_at: string;
}

// Read-only subset of MarketplaceSettings that any authenticated student can
// fetch (MarketplaceSettings itself is admin-only) - just enough for the
// Sell Book form to show the real commission rate and price cap.
export interface MarketplacePricingPolicy {
  platform_commission_percentage: string;
  max_used_book_price_percent: string;
}

export interface MarketplaceRevenueTrendPoint {
  date: string;
  revenue: number;
}

export interface MarketplacePaymentMethodBreakdown {
  method: string;
  count: number;
  percentage: number;
}

export interface MarketplaceOverview {
  totalProducts: number;
  activeProducts: number;
  totalOrders: number;
  pendingOrders: number;
  completedOrders: number;
  cancelledOrders: number;
  revenue: number;
  revenueToday: number;
  revenueTrend: MarketplaceRevenueTrendPoint[];
  paymentMethodBreakdown: MarketplacePaymentMethodBreakdown[];
  recentOrders: Array<{
    id: number;
    product: string;
    buyer: string;
    seller: string;
    price: number;
    status: string;
    createdAt: string;
  }>;
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------


export interface Review {
  id: number;
  order_item: number;
  product: number;
  buyer: number;
  seller: number;
  rating: number;
  review_text: string;
  status: 'PUBLISHED' | 'HIDDEN' | 'FLAGGED';
  created_at: string;
}

export interface DisputeEvidence {
  id: number;
  image: string;
  uploaded_by: number;
  created_at: string;
}

export interface Dispute {
  id: number;
  order_item: number;
  buyer: number;
  seller: number;
  reason: string;
  description: string;
  status: 'OPEN' | 'UNDER_REVIEW' | 'RESOLVED' | 'REJECTED';
  resolution?: string;
  admin_notes?: string;
  evidence: DisputeEvidence[];
  created_at: string;
  resolved_at?: string;
  resolved_by?: number;
}

export interface PayoutAccount {
  id: number;
  seller: number;
  method: "ESEWA" | "KHALTI" | "BANK";
  method_display?: string;
  account_name: string;
  account_identifier: string;
  bank_name?: string;
  branch?: string;
  is_verified: boolean;
  is_default: boolean;
  created_at: string;
}

export interface SellerPayout {
  id: number;
  seller: number;
  seller_name?: string;
  payout_account: number;
  payout_account_details?: PayoutAccount;
  requested_amount: string;
  status: "PENDING" | "APPROVED" | "PROCESSING" | "PAID" | "REJECTED" | "FAILED" | "CANCELLED";
  status_display?: string;
  admin_note?: string;
  rejection_reason?: string;
  transaction_reference?: string;
  processed_by?: number;
  processed_by_name?: string;
  processed_at?: string;
  created_at: string;
}

export interface SellerBalance {
  total_earnings: string;
  pending_payouts: string;
  paid_out: string;
  available_balance: string;
  minimum_payout_amount: string;
}

export const marketplaceApi = {
  // Student - Products (browse)
  getProducts: async (params?: {
    category?: string;
    condition?: string;
    seller_type?: "student" | "platform" | "all";
    location?: string;
    min_price?: string;
    max_price?: string;
    search?: string;
    sort?: string;
    page?: number;
    page_size?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.category) query.append("category", params.category);
    if (params?.condition) query.append("condition", params.condition);
    if (params?.seller_type && params.seller_type !== "all")
      query.append("seller_type", params.seller_type);
    if (params?.location) query.append("location", params.location);
    if (params?.min_price) query.append("min_price", params.min_price);
    if (params?.max_price) query.append("max_price", params.max_price);
    if (params?.search) query.append("search", params.search);
    if (params?.sort) query.append("sort", params.sort);
    if (params?.page) query.append("page", params.page.toString());
    if (params?.page_size) query.append("page_size", params.page_size.toString());
    const qs = query.toString();
    const res = await apiClient<Product[] | { results: Product[]; count: number }>(
      `/marketplace/student/products/${qs ? `?${qs}` : ""}`
    );
    return Array.isArray(res) ? res : (res?.results ?? []);
  },
  getProduct: async (id: number) => {
    return apiClient<Product>(`/marketplace/student/products/${id}/`);
  },

  // Student - Payment Methods
  getPaymentMethods: async () => {
    const res = await apiClient<PaymentMethod[] | { results: PaymentMethod[] }>("/marketplace/student/payment-methods/");
    return Array.isArray(res) ? res : (res?.results ?? []);
  },

  // Student - Payment Submissions
  getSubmissions: async () => {
    const res = await apiClient<PaymentSubmission[] | { results: PaymentSubmission[] }>(
      "/marketplace/student/payment-submissions/"
    );
    return Array.isArray(res) ? res : (res?.results ?? []);
  },
  submitPayment: async (data: FormData) => {
    return apiClient<PaymentSubmission>(
      "/marketplace/student/payment-submissions/",
      { method: "POST", body: data, timeoutMs: 90000 }
    );
  },

  // Student - Purchases
  getPurchases: async () => {
    const res = await apiClient<Purchase[] | { results: Purchase[] }>("/marketplace/student/purchases/");
    return Array.isArray(res) ? res : (res?.results ?? []);
  },

  // Student - Cart
  getCart: async () => {
    return apiClient<Cart>("/marketplace/student/cart/");
  },
  addToCart: async (product_id: number, quantity: number = 1) => {
    // NOTE: backend expects `product_id` (not `product`)
    return apiClient<Cart>("/marketplace/student/cart/add_item/", {
      method: "POST",
      body: JSON.stringify({ product_id, quantity }),
    });
  },
  removeFromCart: async (item_id: number) => {
    return apiClient<Cart>("/marketplace/student/cart/remove_item/", {
      method: "POST",
      body: JSON.stringify({ item_id }),
    });
  },
  // Legacy compat: update cart item quantity
  updateCartItem: async (id: number, quantity: number) => {
    return apiClient<CartItem>(`/marketplace/student/cart/items/${id}/`, {
      method: "PATCH",
      body: JSON.stringify({ quantity }),
    });
  },

  // Student - Orders
  getOrders: async () => {
    const res = await apiClient<Order[] | { results: Order[] }>("/marketplace/student/orders/");
    return Array.isArray(res) ? res : (res?.results ?? []);
  },
  getOrder: async (id: number) => {
    return apiClient<Order>(`/marketplace/student/orders/${id}/`);
  },
  cancelOrder: async (id: number) => {
    return apiClient<Order>(`/marketplace/student/orders/${id}/cancel/`, {
      method: "POST",
    });
  },
  holdOrder: async (id: number, reason?: string) => {
    return apiClient<Order>(`/marketplace/student/orders/${id}/hold/`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || "" }),
    });
  },
  getNCMBranches: async (params?: {
    district?: string;
    municipality?: string;
    province?: string;
    tole?: string;
    latitude?: number;
    longitude?: number;
    allow_nearby?: boolean;
  }) => {
    const q = new URLSearchParams();
    if (params?.district) q.append("district", params.district);
    if (params?.municipality) q.append("municipality", params.municipality);
    if (params?.province) q.append("province", params.province);
    if (params?.tole) q.append("tole", params.tole);
    if (params?.latitude !== undefined && params?.latitude !== null) q.append("latitude", String(params.latitude));
    if (params?.longitude !== undefined && params?.longitude !== null) q.append("longitude", String(params.longitude));
    if (params?.allow_nearby) q.append("allow_nearby", "true");
    const qs = q.toString() ? `?${q.toString()}` : "";
    return apiClient<NCMBranchesResponse>(`/marketplace/student/orders/ncm-branches/${qs}`);
  },
  calculateFee: async (data: {
    delivery_address_id?: number;
    product_id?: number;
    province?: string;
    district?: string;
    municipality?: string;
    destination_branch?: string;
    delivery_type?: string;
  }) => {
    return apiClient<DeliveryFeeResponse>(
      "/marketplace/student/orders/calculate_fee/",
      { method: "POST", body: JSON.stringify(data) }
    );
  },
  createOrder: async (data: {
    delivery_address_id?: number;
    delivery_address?: Partial<DeliveryAddress>;
    shipping_address?: string;
    contact_number?: string;
    destination_branch?: string;
    delivery_type?: string;
    note?: string;
    save_to_addresses?: boolean;
    is_default?: boolean;
    payment_mode?: "PREPAID" | "COD";
  }) => {
    const payload = { ...data };
    if (data.delivery_address) {
      const a = data.delivery_address;
      if (!payload.contact_number && a.phone_number) {
        payload.contact_number = a.phone_number;
      }
      if (!payload.shipping_address) {
        payload.shipping_address = [
          a.full_name,
          a.phone_number,
          `${a.province || ''}, ${a.district || ''}, ${a.municipality || ''}-${a.ward_number || ''}`,
          a.tole_area,
          a.street_landmark ? `Landmark: ${a.street_landmark}` : '',
          a.delivery_note ? `Note: ${a.delivery_note}` : ''
        ].filter(Boolean).join('\n');
      }
    }

    try {
      return await apiClient<Order>("/marketplace/student/orders/checkout/", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } catch (err: any) {
      // If /checkout/ fails or returns 404/500, fallback to standard /orders/
      if (err?.status === 404 || err?.status === 500) {
        return apiClient<Order>("/marketplace/student/orders/", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      throw err;
    }
  },
  switchPaymentMode: async (orderId: number, payment_mode: "PREPAID" | "COD") => {
    return apiClient<Order>(`/marketplace/student/orders/${orderId}/switch-payment-mode/`, {
      method: "POST",
      body: JSON.stringify({ payment_mode }),
    });
  },
  getProfileAddress: async (): Promise<ProfileAddressResponse> => {
    // 1. Primary: dedicated delivery profile endpoint from backend
    try {
      const res = await apiClient<ProfileAddressResponse>(
        "/marketplace/student/delivery-addresses/profile-address/"
      );
      if (res && typeof res === "object" && (res.full_name || res.phone_number || res.district)) {
        return res;
      }
    } catch (primaryErr) {
      console.warn("Delivery profile endpoint unavailable, falling back to registered student profile:", primaryErr);
    }

    // 2. Secondary fallback: student profile endpoint (/support/profile/)
    // Directly extracts registration information entered during signup (name, phone, permanent_district, permanent_local_level)
    try {
      const profile = await apiClient<any>("/support/profile/");
      const fullName =
        (typeof profile?.full_name === "string" && profile.full_name.trim()) ||
        `${profile?.first_name || ""} ${profile?.last_name || ""}`.trim() ||
        (typeof profile?.username === "string" ? profile.username.trim() : "");
      const phone = typeof profile?.phone === "string" ? profile.phone.trim() : "";
      const district = typeof profile?.permanent_district === "string" ? profile.permanent_district.trim() : "";
      const municipality = typeof profile?.permanent_local_level === "string" ? profile.permanent_local_level.trim() : "";
      const province = district ? getProvinceForDistrict(district) : "";

      const missing: string[] = [];
      if (!fullName) missing.push("full_name");
      if (!phone) missing.push("phone_number");
      if (!province) missing.push("province");
      if (!district) missing.push("district");
      if (!municipality) missing.push("municipality");
      missing.push("ward_number", "tole_area");

      return {
        full_name: fullName,
        phone_number: phone,
        province,
        district,
        municipality,
        ward_number: "",
        tole_area: "",
        street_landmark: "",
        delivery_note: "",
        missing_fields: missing,
        is_profile_complete: false,
      };
    } catch (profileErr) {
      console.warn("Student support profile endpoint unavailable:", profileErr);
    }

    // 3. Fallback: current logged-in user in localStorage
    if (typeof window !== "undefined") {
      try {
        const stored = localStorage.getItem("loksewa_auth_user");
        if (stored) {
          const user = JSON.parse(stored);
          const fullName =
            (typeof user?.full_name === "string" && user.full_name.trim()) ||
            (typeof user?.name === "string" && user.name.trim()) ||
            `${user?.first_name || ""} ${user?.last_name || ""}`.trim() ||
            (typeof user?.username === "string" ? user.username.trim() : "");
          const phone = typeof user?.phone === "string" ? user.phone.trim() : "";
          const district = typeof user?.permanent_district === "string" ? user.permanent_district.trim() : "";
          const municipality = typeof user?.permanent_local_level === "string" ? user.permanent_local_level.trim() : "";
          const province = district ? getProvinceForDistrict(district) : "";

          const missing: string[] = [];
          if (!fullName) missing.push("full_name");
          if (!phone) missing.push("phone_number");
          if (!province) missing.push("province");
          if (!district) missing.push("district");
          if (!municipality) missing.push("municipality");
          missing.push("ward_number", "tole_area");

          return {
            full_name: fullName,
            phone_number: phone,
            province,
            district,
            municipality,
            ward_number: "",
            tole_area: "",
            street_landmark: "",
            delivery_note: "",
            missing_fields: missing,
            is_profile_complete: false,
          };
        }
      } catch (storageErr) {
        // ignore
      }
    }

    return {
      full_name: "",
      phone_number: "",
      province: "",
      district: "",
      municipality: "",
      ward_number: "",
      tole_area: "",
      street_landmark: "",
      delivery_note: "",
      missing_fields: ["full_name", "phone_number", "province", "district", "municipality", "ward_number", "tole_area"],
      is_profile_complete: false,
    };
  },

  // Student - Delivery Addresses
  getDeliveryAddresses: async () => {
    const res = await apiClient<DeliveryAddress[] | { results: DeliveryAddress[] }>(
      "/marketplace/student/delivery-addresses/"
    );
    return Array.isArray(res) ? res : (res?.results ?? []);
  },
  createDeliveryAddress: async (data: Partial<DeliveryAddress>) => {
    return apiClient<DeliveryAddress>(
      "/marketplace/student/delivery-addresses/",
      { method: "POST", body: JSON.stringify(data) }
    );
  },
  updateDeliveryAddress: async (id: number, data: Partial<DeliveryAddress>) => {
    return apiClient<DeliveryAddress>(
      `/marketplace/student/delivery-addresses/${id}/`,
      { method: "PATCH", body: JSON.stringify(data) }
    );
  },
  deleteDeliveryAddress: async (id: number) => {
    return apiClient(`/marketplace/student/delivery-addresses/${id}/`, {
      method: "DELETE",
    });
  },

  // Student - My Listings (seller)
  getMyListings: async () => {
    const res = await apiClient<Product[] | { results: Product[] }>("/marketplace/student/my-listings/");
    return Array.isArray(res) ? res : (res?.results ?? []);
  },
  createListing: async (data: FormData) => {
    return apiClient<Product>("/marketplace/student/my-listings/", {
      method: "POST",
      body: data,
    });
  },
  updateListing: async (id: number, data: FormData | Partial<Product>) => {
    const isFormData = data instanceof FormData;
    return apiClient<Product>(`/marketplace/student/my-listings/${id}/`, {
      method: "PATCH",
      body: isFormData ? (data as FormData) : JSON.stringify(data),
    });
  },
  deleteListing: async (id: number) => {
    return apiClient(`/marketplace/student/my-listings/${id}/`, {
      method: "DELETE",
    });
  },
  archiveListing: async (id: number) => {
    return apiClient<Product>(
      `/marketplace/student/my-listings/${id}/archive/`,
      { method: "POST" }
    );
  },
  resubmitListing: async (id: number) => {
    return apiClient<Product>(
      `/marketplace/student/my-listings/${id}/resubmit/`,
      { method: "POST" }
    );
  },

  // Student - My Sales (seller sees their sold orders)
  getMySales: async () => {
    const res = await apiClient<SellerSale[] | { results: SellerSale[] }>("/marketplace/student/my-sales/");
    return Array.isArray(res) ? res : (res?.results ?? []);
  },

  // Student - Listing Reports
  reportListing: async (data: {
    listing: number;
    reason: string;
    description?: string;
  }) => {
    return apiClient<MarketplaceListingReport>(
      "/marketplace/student/listing-reports/",
      { method: "POST", body: JSON.stringify(data) }
    );
  },
  getMyReports: async () => {
    return apiClient<MarketplaceListingReport[]>(
      "/marketplace/student/listing-reports/"
    );
  },

  // Admin - Products
  adminGetProducts: async (params?: {
    listing_status?: string;
    is_seller_listing?: "true" | "false";
  }) => {
    const query = new URLSearchParams();
    if (params?.listing_status)
      query.append("listing_status", params.listing_status);
    if (params?.is_seller_listing)
      query.append("is_seller_listing", params.is_seller_listing);
    const qs = query.toString();
    return apiClient<Product[]>(
      `/marketplace/admin/products/${qs ? `?${qs}` : ""}`
    );
  },
  adminCreateProduct: async (data: FormData) => {
    return apiClient<Product>("/marketplace/admin/products/", {
      method: "POST",
      body: data,
    });
  },
  adminUpdateProduct: async (id: number, data: FormData | Partial<Product>) => {
    const isFormData = data instanceof FormData;
    return apiClient<Product>(`/marketplace/admin/products/${id}/`, {
      method: "PATCH",
      body: isFormData ? (data as FormData) : JSON.stringify(data),
    });
  },
  adminDeleteProductImage: async (productId: number, imageId: number) => {
    return apiClient<Product>(`/marketplace/admin/products/${productId}/delete-image/`, {
      method: "POST",
      body: JSON.stringify({ image_id: imageId }),
    });
  },
  adminSetPrimaryProductImage: async (productId: number, imageId: number) => {
    return apiClient<Product>(`/marketplace/admin/products/${productId}/set-primary-image/`, {
      method: "POST",
      body: JSON.stringify({ image_id: imageId }),
    });
  },
  adminUploadProductImages: async (productId: number, formData: FormData) => {
    return apiClient<Product>(`/marketplace/admin/products/${productId}/upload-images/`, {
      method: "POST",
      body: formData,
    });
  },
  adminDeleteProduct: async (id: number) => {
    return apiClient(`/marketplace/admin/products/${id}/`, { method: "DELETE" });
  },
  adminApproveListing: async (id: number) => {
    return apiClient<Product>(`/marketplace/admin/products/${id}/approve/`, {
      method: "POST",
    });
  },
  adminRejectListing: async (id: number, reason?: string) => {
    return apiClient<Product>(`/marketplace/admin/products/${id}/reject/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },
  adminArchiveListing: async (id: number) => {
    return apiClient<Product>(`/marketplace/admin/products/${id}/archive/`, {
      method: "POST",
    });
  },

  // Admin - Payment Methods
  adminGetPaymentMethods: async () => {
    return apiClient<PaymentMethod[]>("/marketplace/admin/payment-methods/");
  },
  adminUpdatePaymentMethod: async (
    id: number,
    data: FormData | Partial<PaymentMethod>
  ) => {
    const isFormData = data instanceof FormData;
    return apiClient<PaymentMethod>(
      `/marketplace/admin/payment-methods/${id}/`,
      {
        method: "PATCH",
        body: isFormData ? (data as FormData) : JSON.stringify(data),
      }
    );
  },
  adminCreatePaymentMethod: async (data: Partial<PaymentMethod>) => {
    return apiClient<PaymentMethod>("/marketplace/admin/payment-methods/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  adminDeletePaymentMethod: async (id: number) => {
    return apiClient(`/marketplace/admin/payment-methods/${id}/`, {
      method: "DELETE",
    });
  },

  // Admin - Payment Submissions
  adminGetSubmissions: async () => {
    return apiClient<PaymentSubmission[]>(
      "/marketplace/admin/payment-submissions/"
    );
  },
  adminReviewSubmission: async (
    id: number,
    status: "APPROVED" | "REJECTED",
    rejection_reason?: string
  ) => {
    return apiClient<PaymentSubmission>(
      `/marketplace/admin/payment-submissions/${id}/review/`,
      { method: "POST", body: JSON.stringify({ status, rejection_reason }) }
    );
  },

  // Admin - Purchases
  adminGetPurchases: async () => {
    return apiClient<Purchase[]>("/marketplace/admin/purchases/");
  },
  adminRevokePurchase: async (id: number) => {
    return apiClient<Purchase>(`/marketplace/admin/purchases/${id}/revoke/`, {
      method: "POST",
    });
  },
  adminReactivatePurchase: async (id: number) => {
    return apiClient<Purchase>(
      `/marketplace/admin/purchases/${id}/reactivate/`,
      { method: "POST" }
    );
  },

  // Admin - Overview
  adminGetOverview: async () => {
    return apiClient<MarketplaceOverview>("/admin/marketplace/");
  },

  // Admin - Delivery Fee Rules
  adminGetDeliveryFeeRules: async () => {
    return apiClient<DeliveryFeeRule[]>("/marketplace/admin/delivery-fees/");
  },
  adminCreateDeliveryFeeRule: async (data: Partial<DeliveryFeeRule>) => {
    return apiClient<DeliveryFeeRule>("/marketplace/admin/delivery-fees/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  adminUpdateDeliveryFeeRule: async (
    id: number,
    data: Partial<DeliveryFeeRule>
  ) => {
    return apiClient<DeliveryFeeRule>(
      `/marketplace/admin/delivery-fees/${id}/`,
      { method: "PATCH", body: JSON.stringify(data) }
    );
  },
  adminDeleteDeliveryFeeRule: async (id: number) => {
    return apiClient(`/marketplace/admin/delivery-fees/${id}/`, {
      method: "DELETE",
    });
  },

  // Admin - Orders
  adminGetOrders: async () => {
    return apiClient<Order[]>("/marketplace/admin/orders/", { timeoutMs: 60000 });
  },
  adminGetOrder: async (id: number) => {
    return apiClient<Order>(`/marketplace/admin/orders/${id}/`, { timeoutMs: 60000 });
  },
  adminUpdateOrderStatus: async (id: number, status: string, note?: string) => {
    return apiClient<Order>(`/marketplace/admin/orders/${id}/update_status/`, {
      method: "POST",
      body: JSON.stringify({ status, note }),
    });
  },
  adminUpdateOrderItemStatus: async (
    orderId: number,
    itemId: number,
    fulfillment_status?: string,
    payout_status?: string
  ) => {
    return apiClient<Order>(`/marketplace/admin/orders/${orderId}/update_item_status/`, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, fulfillment_status, payout_status }),
    });
  },
  adminDispatchNCM: async (
    orderId: number,
    data?: {
      destination_branch?: string;
      origin_branch?: string;
      package_description?: string;
      weight?: number;
      delivery_type?: string;
      special_instruction?: string;
    }
  ) => {
    return apiClient<Order>(`/marketplace/admin/orders/${orderId}/dispatch-ncm/`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    });
  },
  adminSyncCourier: async (orderId: number) => {
    return apiClient<Order>(`/marketplace/admin/orders/${orderId}/sync-courier/`, {
      method: "POST",
    });
  },
  adminRetryDispatch: async (orderId: number) => {
    return apiClient<Order>(`/marketplace/admin/orders/${orderId}/retry-dispatch/`, {
      method: "POST",
    });
  },
  adminReconcileDispatch: async (
    orderId: number,
    data?: { ncm_order_id?: string; reset_to_failed?: boolean }
  ) => {
    return apiClient<Order>(`/marketplace/admin/orders/${orderId}/reconcile-dispatch/`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    });
  },

  // Admin - Marketplace Settings
  adminGetMarketplaceSettings: async () => {
    return apiClient<MarketplaceSettings>("/marketplace/admin/settings/");
  },
  adminUpdateMarketplaceSettings: async (
    data: Partial<MarketplaceSettings>
  ) => {
    return apiClient<MarketplaceSettings>("/marketplace/admin/settings/", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  // Student - Pricing policy (real commission %, real used-book price cap)
  getPricingPolicy: async () => {
    return apiClient<MarketplacePricingPolicy>(
      "/marketplace/student/pricing-policy/"
    );
  },

  // Admin - Listing Reports
  adminGetListingReports: async () => {
    return apiClient<MarketplaceListingReport[]>(
      "/marketplace/admin/listing-reports/"
    );
  },
  adminReviewListingReport: async (
    id: number,
    status: "REVIEWED" | "DISMISSED",
    admin_response?: string
  ) => {
    return apiClient<MarketplaceListingReport>(
      `/marketplace/admin/listing-reports/${id}/review/`,
      { method: "POST", body: JSON.stringify({ status, admin_response }) }
    );
  },

  // Student - Reviews
  getReviews: async () => {
    return apiClient<Review[]>("/marketplace/student/reviews/");
  },
  createReview: async (data: Partial<Review>) => {
    return apiClient<Review>("/marketplace/student/reviews/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  
  // Student - Disputes
  getDisputes: async () => {
    return apiClient<Dispute[]>("/marketplace/student/disputes/");
  },
  createDispute: async (data: Partial<Dispute>) => {
    return apiClient<Dispute>("/marketplace/student/disputes/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  // Admin - Reviews
  adminGetReviews: async () => {
    return apiClient<Review[]>("/marketplace/admin/reviews/");
  },
  adminUpdateReview: async (id: number, data: Partial<Review>) => {
    return apiClient<Review>(
      `/marketplace/admin/reviews/${id}/`,
      { method: "PATCH", body: JSON.stringify(data) }
    );
  },
  adminDeleteReview: async (id: number) => {
    return apiClient(`/marketplace/admin/reviews/${id}/`, { method: "DELETE" });
  },

  // Admin - Disputes
  adminGetDisputes: async () => {
    return apiClient<Dispute[]>("/marketplace/admin/disputes/");
  },
  adminResolveDispute: async (id: number, status: "RESOLVED" | "REJECTED", resolution: string) => {
    return apiClient<Dispute>(
      `/marketplace/admin/disputes/${id}/resolve/`,
      { method: "POST", body: JSON.stringify({ status, resolution }) }
    );
  },

  // Student - Payouts
  getPayoutBalance: async () => {
    return apiClient<SellerBalance>("/marketplace/student/payouts/balance/");
  },
  getPayoutAccounts: async () => {
    return apiClient<PayoutAccount[]>("/marketplace/student/payout-accounts/");
  },
  createPayoutAccount: async (data: Partial<PayoutAccount>) => {
    return apiClient<PayoutAccount>("/marketplace/student/payout-accounts/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  deletePayoutAccount: async (id: number) => {
    return apiClient(`/marketplace/student/payout-accounts/${id}/`, { method: "DELETE" });
  },
  requestPayout: async (data: { requested_amount: string | number; payout_account_id: number }) => {
    return apiClient<SellerPayout>("/marketplace/student/payouts/request/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  getPayoutHistory: async () => {
    return apiClient<SellerPayout[]>("/marketplace/student/payouts/");
  },

  // Admin - Payouts
  adminGetPayouts: async () => {
    return apiClient<SellerPayout[]>("/marketplace/admin/payouts/");
  },
  adminUpdatePayoutStatus: async (
    id: number,
    status: SellerPayout["status"],
    admin_note?: string,
    rejection_reason?: string,
    transaction_reference?: string
  ) => {
    return apiClient<SellerPayout>(`/marketplace/admin/payouts/${id}/update_status/`, {
      method: "POST",
      body: JSON.stringify({ status, admin_note, rejection_reason, transaction_reference }),
    });
  },

  // -------------------------------------------------------------------------
  // Admin — Nepal Can Move & Courier Operations (Phase 10)
  // -------------------------------------------------------------------------

  adminGetCourierSettings: async () => {
    return apiClient<NCMConfiguration>("/marketplace/admin/courier/settings/");
  },

  adminUpdateCourierSettings: async (data: Partial<NCMConfiguration> & { confirm_production?: boolean }) => {
    return apiClient<NCMConfiguration>("/marketplace/admin/courier/settings/", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  adminTestNCMConnection: async () => {
    return apiClient<{
      success: boolean;
      latency_ms: number | null;
      branch_count?: number;
      environment: string;
      error?: string;
      base_url?: string;
      default_origin_branch?: string;
    }>("/marketplace/admin/courier/test-connection/", {
      method: "POST",
    });
  },

  adminGetCourierBranches: async (params?: { search?: string; status?: string; coord_status?: string; force_refresh?: boolean }) => {
    const sp = new URLSearchParams();
    if (params?.search) sp.set("search", params.search);
    if (params?.status) sp.set("status", params.status);
    if (params?.coord_status) sp.set("coord_status", params.coord_status);
    if (params?.force_refresh) sp.set("force_refresh", "true");
    const qs = sp.toString();
    return apiClient<{ count: number; branches: NCMBranch[]; cached: boolean }>(
      `/marketplace/admin/courier/branches/${qs ? `?${qs}` : ""}`
    );
  },

  adminRefreshCourierBranches: async () => {
    return apiClient<{ count: number; branches: NCMBranch[]; refreshed: boolean; cached: boolean }>(
      "/marketplace/admin/courier/branches/",
      { method: "POST" }
    );
  },

  adminUpdateCourierBranchCoordinates: async (data: {
    id?: number;
    code?: string;
    latitude?: number | null;
    longitude?: number | null;
    coordinate_source?: string;
    is_coordinate_verified?: boolean;
    is_serviceable?: boolean;
    serviceability_notes?: string;
    reason?: string;
  }) => {
    return apiClient<NCMBranch>("/marketplace/admin/courier/branches/", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  adminGetNCMWebhookManagement: async () => {
    return apiClient<{
      webhook_endpoint_url: string;
      webhook_secret_configured: boolean;
      webhook_secret_status: string;
      webhook_enabled: boolean;
      webhook_registered: boolean;
      last_webhook_received_at: string | null;
      last_webhook_event: string;
      last_webhook_error: string;
      recent_events: NCMWebhookEvent[];
    }>("/marketplace/admin/courier/webhook-management/");
  },

  adminActionNCMWebhook: async (action: "toggle_enabled" | "toggle_registered") => {
    return apiClient<any>("/marketplace/admin/courier/webhook-management/", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  },

  adminGetCourierOverview: async () => {
    return apiClient<CourierOverviewData>("/marketplace/admin/courier/overview/");
  },

  adminGetCourierShipments: async (params?: {
    status?: string;
    destination_branch?: string;
    search?: string;
    page?: number;
    page_size?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.status) q.append("status", params.status);
    if (params?.destination_branch) q.append("destination_branch", params.destination_branch);
    if (params?.search) q.append("search", params.search);
    if (params?.page) q.append("page", String(params.page));
    if (params?.page_size) q.append("page_size", String(params.page_size));
    const qs = q.toString() ? `?${q.toString()}` : "";
    return apiClient<{ count?: number; results?: CourierShipment[] } | CourierShipment[]>(
      `/marketplace/admin/courier/shipments/${qs}`
    );
  },

  adminGetCourierShipmentDetail: async (id: number) => {
    return apiClient<CourierShipment>(`/marketplace/admin/courier/shipments/${id}/`);
  },

  adminSyncShipment: async (id: number) => {
    return apiClient<CourierShipment>(`/marketplace/admin/courier/shipments/${id}/sync/`, {
      method: "POST",
    });
  },

  adminTriggerCourierSync: async (limit: number = 50) => {
    return apiClient<{
      success: boolean;
      status: string;
      shipments_checked: number;
      shipments_updated: number;
      errors_count: number;
      log_id: number;
      timestamp: string;
    }>("/marketplace/admin/courier/sync/", {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
  },

  adminGetCourierSyncLogs: async () => {
    return apiClient<CourierSyncLog[]>("/marketplace/admin/courier/sync/");
  },

  adminGetCODRemittances: async (params?: {
    status?: string;
    order_id?: number | string;
    search?: string;
    page?: number;
    page_size?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.status) q.append("status", params.status);
    if (params?.order_id) q.append("order_id", String(params.order_id));
    if (params?.search) q.append("search", params.search);
    if (params?.page) q.append("page", String(params.page));
    if (params?.page_size) q.append("page_size", String(params.page_size));
    const qs = q.toString() ? `?${q.toString()}` : "";
    return apiClient<{ count?: number; results?: CODRemittance[] } | CODRemittance[]>(
      `/marketplace/admin/courier/cod-remittance/${qs}`
    );
  },

  adminVerifyCODRemittance: async (
    id: number,
    data: { remitted_amount?: number | string; reference_number?: string; notes?: string }
  ) => {
    return apiClient<CODRemittance>(`/marketplace/admin/courier/cod-remittance/${id}/verify/`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  adminFlagCODRemittanceDiscrepancy: async (
    id: number,
    data: { discrepancy_reason: string; courier_reported_amount?: number | string; notes?: string }
  ) => {
    return apiClient<CODRemittance>(
      `/marketplace/admin/courier/cod-remittance/${id}/mark-discrepancy/`,
      {
        method: "POST",
        body: JSON.stringify(data),
      }
    );
  },

};
