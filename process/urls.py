# process/urls.py

from django.urls import path
from . import views

app_name = 'process'

urlpatterns = [
    path('', views.process_list, name='process_list'),
    path('add/', views.process_add, name='process_add'),
    path('<int:pk>/edit/', views.process_edit, name='process_edit'),
    path('<int:pk>/delete/', views.process_delete, name='process_delete'),

    # 작업표준서 이력 관련 처리 (inline 방식)
    path('<int:process_id>/file/<int:file_id>/update/', views.process_file_update, name='process_file_update'),
    path('<int:process_id>/file/<int:file_id>/delete/', views.process_file_delete, name='process_file_delete'),
    path('<int:process_id>/file/latest/download/', views.process_file_download, name='process_file_download'),
]


