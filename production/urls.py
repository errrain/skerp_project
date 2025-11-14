# production/urls.py
from django.urls import path, include

app_name = "production"

urlpatterns = [
    path("orders/", include(("production.orders.urls", "orders"), namespace="orders")),
    path("exec/", include(("production.exec.urls", "exec"), namespace="exec")),  # ← 이렇게 고치면 완벽 매칭
    path("finish/", include(("production.finish.urls", "finish"), namespace="finish")),
    path("spares/", include(("production.spares.urls", "spares"), namespace="spares")),
    path("chemadd/", include(("production.chemadd.urls", "chemadd"), namespace="chemadd")),
    # 후개발 모듈 연결 예정:
    # path("complete/", include("production.complete.urls")),
    # path("nonferrous/", include("production.nonferrous.urls")),
    # path("chemicals/", include("production.chemicals.urls")),
    # path("maintenance/", include("production.maintenance.urls")),


]