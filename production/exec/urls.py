# production/exec/urls.py
from django.urls import path
from . import views

app_name = "exec"

urlpatterns = [
    path("", views.exec_list, name="list"),         # 생산진행 메인
    path("start/<int:pk>/", views.exec_start, name="start"),  # 대기→진행중
]