from django.urls import path
from . import views

app_name = 'injection'

urlpatterns = [
    # 리스트, 등록, 수정
    path('', views.injection_list, name='injection_list'),
    path('add/', views.injection_add, name='injection_add'),
    path('<int:pk>/edit/', views.injection_edit, name='injection_edit'),

    # 단가 탭
    path('<int:pk>/price/', views.injection_price_view, name='injection_price'),

    # 금형 이력 탭
    path('<int:pk>/mold/', views.mold_history_view, name='mold_history'),
]
