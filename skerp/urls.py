# skerp_project/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # ✅ 코어/마스터/기초정보
    path('', include('core.urls')),
    path('master/', include('master.urls')),
    path('userinfo/', include('userinfo.urls')),                    # ✅ 사용자 정보
    path('vendor/', include('vendor.urls')),                        # ✅ 거래처 정보
    path('mastercode/', include('mastercode.urls')),                # ✅ 코드 관리
    path('equipment/', include('equipment.urls')),                  # ✅ 설비 관리
    path('process/', include('process.urls')),                      # ✅ 공정 관리
    path('spec/', include('spec.urls')),                            # ✅ 제조 사양
    path('qualityitems/', include('qualityitems.urls')),            # ✅ 품질검사항목
    path('product/', include('product.urls')),                      # ✅ 제품 정보
    path('chemical/', include('chemical.urls')),                    # ✅ 약품 정보
    path('nonferrous/', include('nonferrous.urls')),                # ✅ 비철 정보
    path('submaterial/', include('submaterial.urls')),              # ✅ 부자재 정보
    path('injection/', include('injection.urls')),                  # ✅ 사출품 정보
    path('sales/', include(('sales.urls', 'sales'), namespace='sales')),  # ✅ 영업 관리
    path('injectionorder/', include('injectionorder.urls')),        # ✅ 구매>사출발주
    path('rack/', include('rack.urls')),                            # ✅ 랙 관리
    path('partner/', include(('partnerorder.urls', 'partnerorder'), namespace='partner')),  # ✅ 협력사 발주
    path('quality/', include(('quality.urls', 'quality'), namespace='quality')),            # ✅ 품질경영
    path("purchase/", include(("purchase.urls", "purchase"), namespace="purchase")),        # ✅ 구매 등록
    path("mis/", include(("mis.urls", "mis"), namespace="mis")),  # 통계

    # ✅ 생산 등록
    path("production/", include("production.urls")),

    # ✅ 생산 > 작업지시(orders) 네임스페이스 등록
    path(
        "production/orders/",
        include(("production.orders.urls", "orders"), namespace="orders"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
