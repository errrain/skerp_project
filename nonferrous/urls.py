from django.urls import path
from . import views

app_name = 'nonferrous'

urlpatterns = [
    path('', views.nonferrous_list, name='nonferrous_list'),
    path('add/', views.nonferrous_add, name='nonferrous_add'),
    path('<int:pk>/edit/', views.nonferrous_edit, name='nonferrous_edit'),
    path('<int:pk>/delete/', views.nonferrous_delete, name='nonferrous_delete'),

    # ✅ 단가 탭 URL 추가
    path('<int:pk>/price/', views.nonferrous_price_view, name='nonferrous_price'),
]
