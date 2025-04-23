# sales/urls.py

from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('order/create/', views.order_create, name='order_create'),
    path('order/', views.order_list, name='order_list'),  # ✅ 수정 완료
    path('order/edit/<int:pk>/', views.order_edit, name='order_edit'),  # ✅ 이 줄 추가!
    path('order/delete/<int:pk>/', views.order_delete, name='order_delete'),  # ✅ 추가
    path('search-products/', views.search_products, name='search_products'),
]