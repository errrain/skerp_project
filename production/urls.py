# production/urls.py
from django.urls import path, include

app_name = "production"

urlpatterns = [
    path("orders/", include(("production.orders.urls", "orders"), namespace="orders")),
    path("exec/", include(("production.exec.urls", "exec"), namespace="exec")),
    path("finish/", include(("production.finish.urls", "finish"), namespace="finish")),
    path("spares/", include(("production.spares.urls", "spares"), namespace="spares")),
    path("chemadd/", include(("production.chemadd.urls", "chemadd"), namespace="chemadd")),
    path("nfadd/", include(("production.nfadd.urls", "nfadd"), namespace="nfadd")),
    # 후개발 모듈 연결 예정:
    # path("complete/", include("production.complete.urls")),
    # path("nonferrous/", include("production.nonferrous.urls")),
    # path("chemicals/", include("production.chemicals.urls")),
    # path("maintenance/", include("production.maintenance.urls")),

]