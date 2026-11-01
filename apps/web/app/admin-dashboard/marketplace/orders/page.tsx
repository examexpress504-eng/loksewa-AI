"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Search, Filter, ShoppingCart, CheckCircle2,
  MoreHorizontal, Eye, Box, MapPin, Loader2, ArrowRight, CreditCard, ExternalLink,
  Truck, RefreshCw, AlertCircle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { marketplaceApi, Order } from "@/lib/api/marketplace";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export default function MarketplaceOrdersPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [actioningId, setActioningId] = useState<number | null>(null);
  
  const [viewOrder, setViewOrder] = useState<Order | null>(null);
  const [newStatus, setNewStatus] = useState<string>("");
  const [statusNote, setStatusNote] = useState<string>("");

  const [dispatching, setDispatching] = useState(false);
  const [syncingCourier, setSyncingCourier] = useState(false);
  const [retryingDispatch, setRetryingDispatch] = useState(false);
  const [reconcilingDispatch, setReconcilingDispatch] = useState(false);
  const [manualNcmOrderId, setManualNcmOrderId] = useState("");
  const [dispatchForm, setDispatchForm] = useState({
    destination_branch: "",
    origin_branch: "Kathmandu",
    weight: 1.0,
    package_description: "",
    delivery_type: "Door2Door",
    special_instruction: "",
  });

  useEffect(() => {
    if (viewOrder) {
      const snap = viewOrder.shipping_address_snapshot || {};
      const desc = viewOrder.items
        ?.map((i) => `${i.quantity}x ${i.product_details?.title || i.snapshot_product_name || 'Book'}`)
        .join(", ") || "Marketplace Books";
      setDispatchForm({
        destination_branch: snap.ncm_branch || snap.district || "",
        origin_branch: "Kathmandu",
        weight: 1.0,
        package_description: desc,
        delivery_type: snap.ncm_delivery_type || "Door2Door",
        special_instruction: "",
      });
    }
  }, [viewOrder]);

  const handleDispatchNCM = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!viewOrder) return;
    if (!dispatchForm.destination_branch.trim()) {
      toast.error("Please specify a valid NCM destination branch.");
      return;
    }

    try {
      setDispatching(true);
      const updatedOrder = await marketplaceApi.adminDispatchNCM(viewOrder.id, {
        destination_branch: dispatchForm.destination_branch.trim(),
        origin_branch: dispatchForm.origin_branch.trim(),
        package_description: dispatchForm.package_description.trim(),
        weight: Number(dispatchForm.weight) || 1.0,
        delivery_type: dispatchForm.delivery_type,
        special_instruction: dispatchForm.special_instruction.trim(),
      });
      toast.success("Shipment successfully created with Nepal Can Move!");
      setViewOrder(updatedOrder);
      await fetchOrders();
    } catch (err: any) {
      toast.error(err?.data?.error || err?.data?.detail || err?.message || "Failed to dispatch NCM shipment.");
    } finally {
      setDispatching(false);
    }
  };

  const handleSyncCourier = async () => {
    if (!viewOrder) return;
    try {
      setSyncingCourier(true);
      const updatedOrder = await marketplaceApi.adminSyncCourier(viewOrder.id);
      toast.success("Courier tracking status refreshed!");
      setViewOrder(updatedOrder);
      await fetchOrders();
    } catch (err: any) {
      toast.error(err?.data?.error || err?.data?.detail || err?.message || "Failed to synchronize courier status.");
    } finally {
      setSyncingCourier(false);
    }
  };

  const handleRetryDispatch = async () => {
    if (!viewOrder) return;
    try {
      setRetryingDispatch(true);
      const updated = await marketplaceApi.adminRetryDispatch(viewOrder.id);
      toast.success("Dispatch retry executed successfully!");
      setViewOrder(updated);
      await fetchOrders();
    } catch (err: any) {
      toast.error(err?.data?.detail || err?.data?.error || err?.message || "Failed to retry dispatch.");
    } finally {
      setRetryingDispatch(false);
    }
  };

  const handleReconcileDispatch = async (resetToFailed = false) => {
    if (!viewOrder) return;
    try {
      setReconcilingDispatch(true);
      const updated = await marketplaceApi.adminReconcileDispatch(viewOrder.id, {
        ncm_order_id: manualNcmOrderId.trim() || undefined,
        reset_to_failed: resetToFailed,
      });
      toast.success(resetToFailed ? "Order dispatch state reset to FAILED for safe re-dispatch." : "Order reconciled with NCM shipment!");
      setViewOrder(updated);
      setManualNcmOrderId("");
      await fetchOrders();
    } catch (err: any) {
      toast.error(err?.data?.detail || err?.data?.error || err?.message || "Reconciliation failed.");
    } finally {
      setReconcilingDispatch(false);
    }
  };

  const fetchOrders = async () => {
    try {
      const data = await marketplaceApi.adminGetOrders();
      setOrders(Array.isArray(data) ? data : ((data as any)?.results || []));
    } catch (error) {
      console.error("Failed to fetch orders:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  const handleUpdateStatus = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!viewOrder || !newStatus) return;
    
    try {
      setActioningId(viewOrder.id);
      await marketplaceApi.adminUpdateOrderStatus(viewOrder.id, newStatus, statusNote);
      toast.success("Order status updated successfully.");
      setStatusNote("");
      await fetchOrders();
      
      // Update local viewOrder to reflect new history
      const updatedOrders = await marketplaceApi.adminGetOrders();
      const updatedOrder = updatedOrders.find(o => o.id === viewOrder.id);
      if (updatedOrder) setViewOrder(updatedOrder);
      
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Failed to update order status");
    } finally {
      setActioningId(null);
    }
  };

  const handleUpdateItemStatus = async (itemId: number, fulfillment_status: string, payout_status: string) => {
    if (!viewOrder) return;
    try {
      await marketplaceApi.adminUpdateOrderItemStatus(viewOrder.id, itemId, fulfillment_status, payout_status);
      toast.success("Item status updated successfully.");
      
      const updatedOrders = await marketplaceApi.adminGetOrders();
      setOrders(updatedOrders);
      const updatedOrder = updatedOrders.find(o => o.id === viewOrder.id);
      if (updatedOrder) setViewOrder(updatedOrder);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Failed to update item status");
    }
  };

  const filteredOrders = orders.filter(o => {
    const matchesSearch = 
      o.id.toString().includes(search) || 
      (o.shipping_address || "").toLowerCase().includes(search.toLowerCase()) ||
      (o.contact_number || "").includes(search);
      
    const matchesStatus = statusFilter === "All" || o.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getOrderStatusColor = (status: string) => {
    switch(status) {
      case "PENDING_PAYMENT": return "bg-slate-100 text-slate-700 border-slate-200";
      case "PAYMENT_SUBMITTED": return "bg-amber-100 text-amber-700 border-amber-200";
      case "PAYMENT_VERIFICATION": return "bg-blue-100 text-blue-700 border-blue-200";
      case "CONFIRMED": return "bg-emerald-100 text-emerald-700 border-emerald-200";
      case "PROCESSING": return "bg-indigo-100 text-indigo-700 border-indigo-200";
      case "SHIPPED": return "bg-purple-100 text-purple-700 border-purple-200";
      case "OUT_FOR_DELIVERY": return "bg-pink-100 text-pink-700 border-pink-200";
      case "DELIVERED": return "bg-green-100 text-green-700 border-green-200";
      case "CANCELLED":
      case "ON_HOLD": return "bg-amber-100 text-amber-800 border-amber-300";
      case "REFUNDED": return "bg-red-100 text-red-700 border-red-200";
      default: return "bg-slate-100 text-slate-600 border-slate-200";
    }
  };

  const statusOptions = [
    "PENDING_PAYMENT", "PAYMENT_SUBMITTED", "PAYMENT_VERIFICATION", 
    "CONFIRMED", "PROCESSING", "ON_HOLD", "SHIPPED", "OUT_FOR_DELIVERY", 
    "DELIVERED", "CANCELLED", "REFUNDED"
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white p-4 rounded-xl shadow-sm border border-slate-200">
        <div className="flex gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <Input
              placeholder="Search Order ID, Address, Contact..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-slate-50"
            />
          </div>
        </div>
        <div className="flex gap-2 w-full sm:w-auto">
          <select 
            className="h-10 px-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#0B2545]/20 flex-1 sm:flex-none"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="All">All Statuses</option>
            {statusOptions.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50 hover:bg-slate-50">
                <TableHead className="w-32">Order ID & Date</TableHead>
                <TableHead>Contact & Address</TableHead>
                <TableHead>Items</TableHead>
                <TableHead className="text-right">Grand Total</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-slate-500">
                    <Loader2 className="w-8 h-8 animate-spin mx-auto" />
                  </TableCell>
                </TableRow>
              ) : filteredOrders.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-slate-500">
                    <ShoppingCart className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                    <p>No orders found.</p>
                  </TableCell>
                </TableRow>
              ) : (
                filteredOrders.map((order) => {
                  return (
                    <TableRow key={order.id} className="hover:bg-slate-50/80">
                      <TableCell>
                        <div className="font-mono text-xs font-semibold text-[#0B2545]">#ORD-{order.id}</div>
                        <div className="text-[11px] text-slate-400 mt-1">{new Date(order.created_at).toLocaleDateString()}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-semibold text-slate-700 text-xs">{order.contact_number}</span>
                          <span className="text-[10px] text-slate-500 truncate max-w-[200px] mt-0.5">{order.shipping_address}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs font-medium text-slate-600 bg-slate-100 px-2 py-1 rounded">
                          {order.items.length} item(s)
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="font-bold text-slate-800">Rs. {Number(order.total_amount) + Number(order.delivery_fee)}</div>
                        {Number(order.delivery_fee) > 0 && <div className="text-[10px] text-slate-400">inc. Rs {order.delivery_fee} del.</div>}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1 items-start">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${getOrderStatusColor(order.status)}`}>
                            {order.status}
                          </span>
                          {(order.status === "PAYMENT_SUBMITTED" || order.status === "PAYMENT_VERIFICATION") && (
                            <button 
                              onClick={() => router.push(`/admin-dashboard/marketplace/payments?order_id=${order.id}`)}
                              className="text-[11px] text-blue-600 hover:text-blue-800 font-medium inline-flex items-center gap-0.5 hover:underline"
                            >
                              Verify now <ArrowRight className="w-2.5 h-2.5" />
                            </button>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {(order.status === "PAYMENT_SUBMITTED" || order.status === "PAYMENT_VERIFICATION" || order.latest_payment_submission) && (
                            <Button 
                              variant="outline" 
                              size="sm" 
                              className="h-8 px-2.5 text-xs text-amber-700 bg-amber-50 hover:bg-amber-100 border-amber-200 flex items-center gap-1 font-semibold"
                              title="Verify Payment"
                              onClick={() => router.push(`/admin-dashboard/marketplace/payments?order_id=${order.id}`)}
                            >
                              <CreditCard className="w-3.5 h-3.5" />
                              Verify
                            </Button>
                          )}
                          <Button 
                            variant="ghost" 
                            size="sm" 
                            onClick={() => {
                              setViewOrder(order);
                              setNewStatus(order.status);
                            }}
                          >
                            Manage
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={!!viewOrder} onOpenChange={(open: boolean) => !open && setViewOrder(null)}>
        <DialogContent className="w-full max-w-2xl overflow-y-auto max-h-[90vh] bg-slate-50">
          {viewOrder && (
            <div className="space-y-8 py-4">
              <DialogHeader>
                <DialogTitle className="text-2xl flex items-center gap-2">
                  <Box className="w-6 h-6 text-primary" /> Order #ORD-{viewOrder.id}
                </DialogTitle>
              </DialogHeader>
              
              <div className="bg-white rounded-xl border p-5 shadow-sm space-y-4">
                <div className="flex justify-between items-center border-b pb-4">
                  <span className={`px-3 py-1 rounded-full text-sm font-bold border ${getOrderStatusColor(viewOrder.status)}`}>
                    {viewOrder.status}
                  </span>
                  <span className="text-sm font-semibold">Total: Rs. {Number(viewOrder.total_amount) + Number(viewOrder.delivery_fee)}</span>
                </div>

                {/* Payment Verification Quick Access Card */}
                <div className="bg-gradient-to-r from-blue-50/90 via-indigo-50/60 to-white border border-blue-200/80 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 bg-[#0B2545] text-amber-400 rounded-lg shrink-0 mt-0.5 sm:mt-0">
                      <CreditCard className="w-5 h-5" />
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-800 text-sm">Payment Verification</span>
                        {viewOrder.latest_payment_submission ? (
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase border ${
                            viewOrder.latest_payment_submission.status === "APPROVED"
                              ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                              : viewOrder.latest_payment_submission.status === "REJECTED"
                              ? "bg-rose-100 text-rose-800 border-rose-300"
                              : "bg-amber-100 text-amber-800 border-amber-300"
                          }`}>
                            Submission: {viewOrder.latest_payment_submission.status}
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600 border border-slate-200">
                            {viewOrder.payment_status || viewOrder.status}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600">
                        {viewOrder.latest_payment_submission?.transaction_id ? (
                          <>
                            Txn ID: <strong className="font-mono text-slate-800">{viewOrder.latest_payment_submission.transaction_id}</strong>
                            {" • "}Submitted: <strong>Rs. {viewOrder.latest_payment_submission.submitted_amount || viewOrder.total_amount}</strong>
                          </>
                        ) : (
                          "View manual payment screenshot, verify transaction, and approve or reject payment."
                        )}
                      </p>
                    </div>
                  </div>

                  <Button 
                    size="sm"
                    className="bg-[#0B2545] hover:bg-[#134074] text-white font-medium text-xs px-3.5 h-9 shrink-0 flex items-center gap-1.5 w-full sm:w-auto shadow-sm"
                    onClick={() => router.push(`/admin-dashboard/marketplace/payments?order_id=${viewOrder.id}`)}
                  >
                    <span>Verify Payment</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Button>
                </div>
                
                {viewOrder.status === 'ON_HOLD' && (
                  <div className="bg-amber-50 border-2 border-amber-300 rounded-lg p-4 text-sm text-amber-900 space-y-1">
                    <div className="font-bold flex items-center gap-2">
                      <span>⚠️ Order is currently ON HOLD</span>
                    </div>
                    {viewOrder.held_at && (
                      <p className="text-xs text-amber-800">
                        Placed on hold on: {new Date(viewOrder.held_at).toLocaleString()}
                      </p>
                    )}
                    {viewOrder.hold_reason && (
                      <p className="text-xs text-amber-900 mt-1">
                        <strong>Reason:</strong> {viewOrder.hold_reason}
                      </p>
                    )}
                    <p className="text-xs text-amber-700 mt-1">
                      Per policy, verified COD advances remain non-refundable. Admin may resume the order to PROCESSING or cancel it.
                    </p>
                  </div>
                )}

                <div>
                  <h4 className="font-semibold text-sm mb-2 flex items-center gap-2 text-slate-700">
                    <MapPin className="w-4 h-4" /> Shipping Address
                  </h4>
                  <p className="text-sm text-slate-600 whitespace-pre-wrap bg-slate-50 p-3 rounded-lg border">
                    {viewOrder.shipping_address}
                    <br/><br/>
                    <strong>Contact:</strong> {viewOrder.contact_number}
                  </p>
                </div>
                
                <div>
                  <h4 className="font-semibold text-sm mb-2 text-slate-700">Order Items (S2S Fulfillment)</h4>
                  <div className="space-y-4">
                    {viewOrder.items.map(item => (
                      <div key={item.id} className="flex flex-col gap-3 bg-slate-50 p-4 rounded-lg border text-sm">
                        <div className="flex justify-between items-start">
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              {(item.product || item.product_details?.id) && (
                                <span className="bg-blue-50 text-[#0B2545] font-mono text-[10px] font-bold px-1.5 py-0.5 rounded border border-blue-200">
                                  Product ID: #{item.product || item.product_details?.id}
                                </span>
                              )}
                            </div>
                            <div className="font-bold text-slate-800">{item.product_details?.title || item.snapshot_product_name || `Product #${item.product}`}</div>
                            <div className="text-slate-500 text-xs mt-1">
                              Qty: {item.quantity} × Rs. {item.price}
                            </div>
                            <div className="text-slate-500 text-xs mt-1">
                              Seller: {item.product_details?.seller_details?.full_name || item.snapshot_seller_name || "LoksewaAI Official"}
                            </div>
                          </div>
                          <div className="text-right text-xs">
                            <div className="text-emerald-600 font-semibold">Earnings: Rs. {item.seller_earning || 0}</div>
                            <div className="text-rose-500 font-medium">Comm: Rs. {item.commission_amount || 0}</div>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4 mt-2 pt-3 border-t border-slate-200">
                          <div className="space-y-1.5">
                            <label className="text-xs font-semibold text-slate-500">Fulfillment Status</label>
                            <Select 
                              value={item.fulfillment_status || "PENDING"} 
                              onValueChange={(val) => handleUpdateItemStatus(item.id, val, item.payout_status || "PENDING")}
                            >
                              <SelectTrigger className="h-8 text-xs bg-white">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"].map(s => (
                                  <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-semibold text-slate-500">Payout Status</label>
                            <Select 
                              value={item.payout_status || "PENDING"} 
                              onValueChange={(val) => handleUpdateItemStatus(item.id, item.fulfillment_status || "PENDING", val)}
                            >
                              <SelectTrigger className="h-8 text-xs bg-white">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {["PENDING", "ELIGIBLE", "PROCESSING", "PAID", "FAILED", "CANCELLED"].map(s => (
                                  <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Nepal Can Move (NCM) Courier & Dispatch Card */}
              <div className="bg-white rounded-xl border p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b pb-3">
                  <div className="flex items-center gap-2">
                    <Truck className="w-5 h-5 text-indigo-600" />
                    <h4 className="font-bold text-slate-800">Nepal Can Move (NCM) Courier</h4>
                  </div>
                  {viewOrder.courier_shipment && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleSyncCourier}
                      disabled={syncingCourier}
                      className="text-xs h-8 flex items-center gap-1.5"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${syncingCourier ? "animate-spin" : ""}`} />
                      Sync Courier Status
                    </Button>
                  )}
                </div>

                {/* Phase 18: Distinct Lifecycle & Dispatch Observability Dashboard */}
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-700">Lifecycle Status:</span>
                      {(() => {
                        const status = (viewOrder as any).dispatch_observability?.lifecycle_status || (viewOrder as any).lifecycle_status || 'PENDING_PAYMENT';
                        const badgeStyles: Record<string, { bg: string, text: string, border: string, label: string }> = {
                          PENDING_PAYMENT: { bg: 'bg-slate-100', text: 'text-slate-700', border: 'border-slate-300', label: 'PENDING PAYMENT' },
                          PAYMENT_VERIFIED: { bg: 'bg-blue-100', text: 'text-blue-800', border: 'border-blue-300', label: 'PAYMENT VERIFIED' },
                          DISPATCH_QUEUED: { bg: 'bg-indigo-100', text: 'text-indigo-800', border: 'border-indigo-300', label: 'DISPATCH QUEUED' },
                          DISPATCH_PROCESSING: { bg: 'bg-sky-100', text: 'text-sky-800', border: 'border-sky-300', label: 'DISPATCH PROCESSING' },
                          DISPATCH_FAILED: { bg: 'bg-rose-100', text: 'text-rose-800', border: 'border-rose-300', label: 'DISPATCH FAILED' },
                          MANUAL_REVIEW_REQUIRED: { bg: 'bg-amber-100', text: 'text-amber-900', border: 'border-amber-400', label: 'MANUAL REVIEW REQUIRED' },
                          NCM_ORDER_CREATED: { bg: 'bg-emerald-100', text: 'text-emerald-800', border: 'border-emerald-300', label: 'NCM ORDER CREATED' },
                          IN_TRANSIT: { bg: 'bg-purple-100', text: 'text-purple-800', border: 'border-purple-300', label: 'IN TRANSIT' },
                          DELIVERED: { bg: 'bg-teal-100', text: 'text-teal-800', border: 'border-teal-300', label: 'DELIVERED' },
                          REMITTANCE_CONFIRMED: { bg: 'bg-green-100', text: 'text-green-900', border: 'border-green-400', label: 'REMITTANCE CONFIRMED' },
                        };
                        const defaultBadge = { bg: 'bg-slate-100', text: 'text-slate-700', border: 'border-slate-300', label: 'PENDING PAYMENT' };
                        const s = badgeStyles[status] ?? defaultBadge;
                        return (
                          <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${s.bg} ${s.text} ${s.border}`}>
                            {s.label}
                          </span>
                        );
                      })()}
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-slate-500">
                      <span>NCM Connection: <strong className={(viewOrder as any).dispatch_observability?.ncm_auth_status === 'connected' ? 'text-emerald-600' : 'text-slate-600'}>
                        {((viewOrder as any).dispatch_observability?.ncm_auth_status || 'untested').toUpperCase()}
                      </strong></span>
                    </div>
                  </div>

                  {/* Telemetry Grid */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Payment Status</div>
                      <div className="font-semibold text-slate-800">
                        {(viewOrder as any).dispatch_observability?.payment_verification_status || (viewOrder.payment_status === 'PAID' ? 'Verified (100%)' : viewOrder.payment_status === 'PARTIALLY_PAID' ? 'Verified (15% Advance)' : 'Unpaid')}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Dispatch Job</div>
                      <div className="font-semibold text-slate-800">
                        {(viewOrder as any).dispatch_observability?.dispatch_job_status || viewOrder.ncm_dispatch_status}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Queue Time</div>
                      <div className="font-mono text-slate-700">
                        {(viewOrder as any).dispatch_observability?.queue_timestamp ? new Date((viewOrder as any).dispatch_observability.queue_timestamp).toLocaleTimeString() : 'N/A'}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Worker Exec Time</div>
                      <div className="font-mono text-slate-700">
                        {(viewOrder as any).dispatch_observability?.worker_execution_timestamp ? new Date((viewOrder as any).dispatch_observability.worker_execution_timestamp).toLocaleTimeString() : 'N/A'}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">NCM Order ID</div>
                      <div className="font-mono font-semibold text-emerald-700">
                        {viewOrder.courier_shipment?.ncm_order_id || (viewOrder as any).dispatch_observability?.ncm_order_id || 'Not created'}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Tracking Reference</div>
                      <div className="font-mono font-semibold text-slate-800">
                        {viewOrder.courier_shipment?.tracking_id || (viewOrder as any).dispatch_observability?.tracking_reference || 'N/A'}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Dispatch Attempts</div>
                      <div className="font-semibold text-slate-800">
                        {(viewOrder as any).dispatch_observability?.dispatch_attempt_count ?? viewOrder.ncm_dispatch_attempts ?? 0}
                      </div>
                    </div>
                    <div className="bg-white p-2 rounded border border-slate-200">
                      <div className="text-slate-400">Next Retry / Recon</div>
                      <div className="text-slate-700 truncate" title={(viewOrder as any).dispatch_observability?.next_retry_status}>
                        {(viewOrder as any).dispatch_observability?.next_retry_status || 'None'}
                      </div>
                    </div>
                  </div>

                  {(viewOrder as any).dispatch_observability?.last_failure_reason && (
                    <div className="bg-rose-50 border border-rose-200 p-2 rounded text-[11px] text-rose-800">
                      <span className="font-bold">Last Error: </span>
                      <span className="font-mono">{(viewOrder as any).dispatch_observability.last_failure_reason}</span>
                    </div>
                  )}
                </div>

                {/* Ambiguous Timeout / Manual Review Card */}
                {viewOrder.ncm_dispatch_status === 'MANUAL_REVIEW_REQUIRED' && !viewOrder.courier_shipment && (
                  <div className="p-4 bg-amber-50 border-2 border-amber-300 rounded-lg text-xs text-amber-950 space-y-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
                      <div className="space-y-1">
                        <strong className="text-amber-900 font-bold">Ambiguous Network Timeout (Duplicate Protection Active)</strong>
                        <p className="text-amber-800 leading-relaxed">
                          The request to NCM timed out after submission. To prevent creating duplicate real shipments, blind retry has been suspended.
                        </p>
                        <p className="text-[11px] font-mono text-amber-800 bg-amber-100/60 p-1.5 rounded border border-amber-200">
                          {viewOrder.ncm_dispatch_last_error}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-amber-200">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => handleReconcileDispatch(false)}
                        disabled={reconcilingDispatch}
                        className="bg-amber-600 hover:bg-amber-700 text-white text-xs h-7 flex items-center gap-1 font-semibold"
                      >
                        <RefreshCw className={`w-3 h-3 ${reconcilingDispatch ? 'animate-spin' : ''}`} />
                        Reconcile with NCM
                      </Button>
                      <div className="flex items-center gap-1">
                        <Input
                          placeholder="NCM Order ID (optional)"
                          value={manualNcmOrderId}
                          onChange={(e) => setManualNcmOrderId(e.target.value)}
                          className="h-7 text-xs w-44 bg-white"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => handleReconcileDispatch(false)}
                          disabled={reconcilingDispatch || !manualNcmOrderId.trim()}
                          className="text-xs h-7 bg-white font-semibold"
                        >
                          Link ID
                        </Button>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => handleReconcileDispatch(true)}
                        disabled={reconcilingDispatch}
                        className="text-[11px] text-amber-800 hover:text-amber-950 underline h-7 ml-auto"
                      >
                        Reset to Failed (No shipment in NCM)
                      </Button>
                    </div>
                  </div>
                )}

                {/* Failed Dispatch Card */}
                {viewOrder.ncm_dispatch_status === 'FAILED' && !viewOrder.courier_shipment && (
                  <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-900 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <strong className="text-rose-800">Automatic Courier Dispatch Failed</strong>
                        <p className="mt-0.5 text-rose-700">
                          {viewOrder.ncm_dispatch_last_error || "An error occurred while communicating with Nepal Can Move."}
                        </p>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        onClick={handleRetryDispatch}
                        disabled={retryingDispatch}
                        className="bg-rose-600 hover:bg-rose-700 text-white text-xs h-7 shrink-0 flex items-center gap-1 font-semibold"
                      >
                        <RefreshCw className={`w-3 h-3 ${retryingDispatch ? 'animate-spin' : ''}`} />
                        Retry Dispatch
                      </Button>
                    </div>
                    <div className="flex items-center gap-4 text-[11px] text-rose-600 border-t border-rose-200/60 pt-1.5">
                      <span>Attempts: <strong>{viewOrder.ncm_dispatch_attempts || 1}</strong></span>
                      {viewOrder.ncm_dispatch_next_retry && (
                        <span>Next Auto-Retry: <strong>{new Date(viewOrder.ncm_dispatch_next_retry).toLocaleTimeString()}</strong></span>
                      )}
                    </div>
                  </div>
                )}

                {/* Queued / Creating Banner */}
                {(viewOrder.ncm_dispatch_status === 'QUEUED' || viewOrder.ncm_dispatch_status === 'CREATING') && !viewOrder.courier_shipment && (
                  <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <RefreshCw className="w-4 h-4 text-blue-600 animate-spin" />
                      <div>
                        <strong>Automatic courier dispatch in progress.</strong>
                        <p className="text-[11px] text-blue-700 mt-0.5">
                          Payment is verified. The background worker is connecting to NCM API to generate tracking code.
                        </p>
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={handleRetryDispatch}
                      disabled={retryingDispatch}
                      className="text-xs h-7 bg-white font-semibold"
                    >
                      Dispatch Now
                    </Button>
                  </div>
                )}

                {viewOrder.courier_shipment ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-50 p-3.5 rounded-lg border text-xs">
                      <div>
                        <span className="text-slate-400 block font-medium">NCM Order ID</span>
                        <span className="font-mono font-bold text-slate-800 text-sm">
                          #{viewOrder.courier_shipment.ncm_order_id}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-medium">Tracking Code</span>
                        <span className="font-mono font-bold text-indigo-600 text-sm">
                          {viewOrder.courier_shipment.tracking_id || "Pending"}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-medium">Courier Status</span>
                        <span className="inline-block mt-0.5 px-2 py-0.5 rounded text-[11px] font-bold bg-indigo-100 text-indigo-800 border border-indigo-200">
                          {viewOrder.courier_shipment.courier_status}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-medium">Route</span>
                        <span className="font-semibold text-slate-700">
                          {viewOrder.courier_shipment.origin_branch} → {viewOrder.courier_shipment.destination_branch}
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs bg-slate-50 p-3.5 rounded-lg border">
                      <div>
                        <span className="text-slate-400 block">COD Collection Amount</span>
                        <span className="font-extrabold text-amber-700 text-sm">
                          Rs. {viewOrder.courier_shipment.cod_charge}
                        </span>
                        <span className="text-[10px] text-slate-400 block">
                          {viewOrder.is_cod ? "(Remaining 85% Balance)" : "(Prepaid Order - No COD)"}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block">Delivery Charge (Quoted / Actual)</span>
                        <span className="font-semibold text-slate-700">
                          Rs. {viewOrder.courier_shipment.quoted_charge} / Rs. {viewOrder.courier_shipment.actual_charge || viewOrder.courier_shipment.quoted_charge}
                        </span>
                        <span className="text-[10px] text-slate-400 block">
                          {viewOrder.courier_shipment.delivery_type} ({viewOrder.courier_shipment.weight} kg)
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block">Last Synced</span>
                        <span className="text-slate-600 font-medium">
                          {viewOrder.courier_shipment.last_synced_at
                            ? new Date(viewOrder.courier_shipment.last_synced_at).toLocaleString()
                            : "Just dispatched"}
                        </span>
                      </div>
                    </div>

                    {viewOrder.courier_shipment.status_history && viewOrder.courier_shipment.status_history.length > 0 && (
                      <div className="border rounded-lg p-3 bg-white space-y-2">
                        <span className="text-xs font-bold text-slate-600 block">Courier Milestones</span>
                        <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                          {viewOrder.courier_shipment.status_history.map((event: any, i: number) => (
                            <div key={i} className="text-xs flex justify-between items-start border-b pb-1 last:border-b-0">
                              <div>
                                <span className="font-semibold text-slate-800">{event.status || event.state || "Update"}</span>
                                {event.remarks && <p className="text-[11px] text-slate-500">{event.remarks}</p>}
                              </div>
                              <span className="text-[10px] text-slate-400 font-mono">
                                {event.timestamp || event.time || ""}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    {/* Check eligibility */}
                    {(viewOrder.status === 'CONFIRMED' || viewOrder.status === 'PROCESSING') &&
                     (!viewOrder.is_cod || viewOrder.payment_status === 'PARTIALLY_PAID') ? (
                      <form onSubmit={handleDispatchNCM} className="space-y-3">
                        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900 flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 shrink-0 text-blue-600 mt-0.5" />
                          <div>
                            <strong>Order is verified and eligible for dispatch.</strong>
                            <p className="mt-0.5">
                              {viewOrder.is_cod
                                ? `NCM will collect remaining 85% COD: Rs. ${viewOrder.cod_remaining_balance} from recipient.`
                                : "Order is 100% prepaid online. NCM COD collection will be Rs. 0.00."}
                            </p>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">Destination Branch *</label>
                            <Input
                              placeholder="e.g. Pokhara, Biratnagar..."
                              value={dispatchForm.destination_branch}
                              onChange={(e) => setDispatchForm({ ...dispatchForm, destination_branch: e.target.value })}
                              required
                              className="h-8 text-xs bg-white"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">Origin Branch</label>
                            <Input
                              placeholder="Kathmandu"
                              value={dispatchForm.origin_branch}
                              onChange={(e) => setDispatchForm({ ...dispatchForm, origin_branch: e.target.value })}
                              className="h-8 text-xs bg-white"
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">Package Weight (kg)</label>
                            <Input
                              type="number"
                              step="0.1"
                              min="0.1"
                              value={dispatchForm.weight}
                              onChange={(e) => setDispatchForm({ ...dispatchForm, weight: parseFloat(e.target.value) || 1.0 })}
                              className="h-8 text-xs bg-white"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">Delivery Type</label>
                            <Select
                              value={dispatchForm.delivery_type}
                              onValueChange={(val) => setDispatchForm({ ...dispatchForm, delivery_type: val })}
                            >
                              <SelectTrigger className="h-8 text-xs bg-white">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="Door2Door" className="text-xs">Door2Door (Standard)</SelectItem>
                                <SelectItem value="Branch2Branch" className="text-xs">Branch2Branch (Hub pickup)</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">Package Description</label>
                            <Input
                              placeholder="Items summary"
                              value={dispatchForm.package_description}
                              onChange={(e) => setDispatchForm({ ...dispatchForm, package_description: e.target.value })}
                              className="h-8 text-xs bg-white"
                            />
                          </div>
                        </div>

                        <div className="space-y-1">
                          <label className="text-xs font-semibold text-slate-600">Special Instructions (Optional)</label>
                          <Input
                            placeholder="e.g. Call before delivery, handle books with care"
                            value={dispatchForm.special_instruction}
                            onChange={(e) => setDispatchForm({ ...dispatchForm, special_instruction: e.target.value })}
                            className="h-8 text-xs bg-white"
                          />
                        </div>

                        <Button
                          type="submit"
                          disabled={dispatching}
                          className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs h-9 mt-2 flex items-center justify-center gap-2"
                        >
                          {dispatching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}
                          Dispatch via Nepal Can Move (NCM)
                        </Button>
                      </form>
                    ) : (
                      <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
                        <div>
                          <strong>Courier dispatch locked.</strong>
                          <p className="mt-0.5">
                            Order must be CONFIRMED or PROCESSING, with verified payment
                            {viewOrder.is_cod ? " (15% advance verified)" : " (full payment verified)"}
                            before a courier dispatch can be created.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="bg-white rounded-xl border p-5 shadow-sm space-y-4">
                <h4 className="font-semibold text-slate-800">Update Status</h4>
                <form onSubmit={handleUpdateStatus} className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-slate-500">New Status</label>
                    <Select value={newStatus} onValueChange={setNewStatus}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select status" />
                      </SelectTrigger>
                      <SelectContent>
                        {statusOptions.map(s => (
                          <SelectItem key={s} value={s}>{s}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-slate-500">Note (Optional)</label>
                    <Textarea 
                      placeholder="Add a tracking number or internal note..." 
                      value={statusNote}
                      onChange={(e) => setStatusNote(e.target.value)}
                    />
                  </div>
                  <Button type="submit" className="w-full" disabled={actioningId !== null || newStatus === viewOrder.status}>
                    {actioningId ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                    Confirm Status Change
                  </Button>
                </form>
              </div>
              
              {viewOrder.status_history && viewOrder.status_history.length > 0 && (
                <div className="bg-white rounded-xl border p-5 shadow-sm space-y-4">
                  <h4 className="font-semibold text-slate-800">Status History</h4>
                  <div className="space-y-4">
                    {viewOrder.status_history.map((history, idx) => (
                      <div key={history.id} className="relative pl-6 border-l-2 border-slate-200 ml-2">
                        <div className="absolute -left-1.5 top-1.5 w-3 h-3 rounded-full bg-slate-300 ring-4 ring-white" />
                        <div className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                          <span className="text-slate-500 line-through">{history.previous_status}</span>
                          <ArrowRight className="w-3 h-3 text-slate-400" />
                          <span className="text-primary">{history.new_status}</span>
                        </div>
                        <div className="text-xs text-slate-500 mt-1">
                          By {history.changed_by_name} on {new Date(history.created_at).toLocaleString()}
                        </div>
                        {history.note && (
                          <div className="mt-2 text-xs bg-slate-50 p-2 rounded border text-slate-600">
                            {history.note}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
