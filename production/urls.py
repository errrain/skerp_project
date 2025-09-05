# production/urls.py
from django.urls import path, include

app_name = "production"

urlpatterns = [
    path("orders/", include(("production.orders.urls", "orders"), namespace="orders")),
    # 후개발 모듈 연결 예정:
    # path("exec/", include("production.exec.urls")),
    # path("complete/", include("production.complete.urls")),
    # path("nonferrous/", include("production.nonferrous.urls")),
    # path("chemicals/", include("production.chemicals.urls")),
    # path("maintenance/", include("production.maintenance.urls")),
    # path("spares/", include("production.spares.urls")),
]