"""Coupon URL routes."""

from django.urls import path

from coupons.views import (
    CouponBatchListCreateView,
    CouponDispatchView,
    CouponListView,
    CouponRedeemView,
    DonorCouponStatsView,
    DonorCouponWalletView,
    ExportCouponsExcelView,
)

app_name = "coupons"

urlpatterns = [
    path("batches/", CouponBatchListCreateView.as_view(), name="coupon-batch-list"),
    path("export/", ExportCouponsExcelView.as_view(), name="coupon-export"),
    path("", CouponListView.as_view(), name="coupon-list"),
    path("wallet/", DonorCouponWalletView.as_view(), name="coupon-wallet"),
    path("stats/", DonorCouponStatsView.as_view(), name="coupon-stats"),
    path("dispatch/", CouponDispatchView.as_view(), name="coupon-dispatch"),
    path("redeem/", CouponRedeemView.as_view(), name="coupon-redeem"),
]
