from django.urls import path
from . import views

app_name = 'chemical'

urlpatterns = [
    path('', views.chemical_list, name='chemical_list'),
    path('add/', views.chemical_add, name='chemical_add'),
    path('<int:pk>/edit/', views.chemical_edit, name='chemical_edit'),
    path('<int:pk>/delete/', views.chemical_delete, name='chemical_delete'),

    # ✅ 단가 탭 URL 추가
    path('<int:pk>/price/', views.chemical_price_view, name='chemical_price'),

    path('export/', views.chemical_export, name='chemical_export'),  # ⬅️ 추가
]
