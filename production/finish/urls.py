# production/finish/urls.py
from django.urls import path
from . import views

app_name = "finish"

urlpatterns = [
    path("", views.finish_list, name="list"),             # 생산완료 메인(목록)
    path("done/<int:pk>/", views.finish_done, name="done"),  # 진행중 → 완료
    path("revert/<int:pk>/", views.finish_revert, name="revert"),
    path("print/<int:pk>/",  views.finish_print,  name="print"),
]