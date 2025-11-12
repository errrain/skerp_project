# production/exec/urls.py
from django.urls import path
from . import views

app_name = "exec"

urlpatterns = [
    path("", views.exec_list, name="list"),                    # 생산진행 메인
    path("start/<int:pk>/", views.exec_start, name="start"),   # 대기→진행중
    # 사출 입고 LOT 후보(사용대기 + sk_wh_9) 조회
    path("lots/<int:pk>/", views.exec_injection_lot_candidates, name="lot_candidates"),
    path("bind-lot/<int:pk>/", views.exec_bind_lot, name="bind_lot"),  # ← 새로 추가
    path("cancel/<int:pk>/",     views.exec_cancel,              name="cancel"),  # ← 추가
]