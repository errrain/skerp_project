
#partnerorder/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('orders/', views.OrderListView.as_view(), name='order_list'),
    path('orders/<int:pk>/register-shipping/', views.register_shipping, name='register_shipping'),
    path('orders/print-qr/', views.print_qr, name='print_qr'),
]