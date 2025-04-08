from django.urls import path
from . import views

app_name = 'submaterial'

urlpatterns = [
    path('', views.submaterial_list, name='submaterial_list'),
    path('add/', views.submaterial_add, name='submaterial_add'),
    path('<int:pk>/edit/', views.submaterial_edit, name='submaterial_edit'),
    path('<int:pk>/delete/', views.submaterial_delete, name='submaterial_delete'),

    # ✅ 단가 탭 URL 추가
    path('<int:pk>/price/', views.submaterial_price_view, name='submaterial_price'),
]
