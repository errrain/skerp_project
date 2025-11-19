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
    path('<int:process_id>/file/<int:file_id>/update/',
         views.process_file_update, name='process_file_update'),
    path('<int:process_id>/file/<int:file_id>/delete/',
         views.process_file_delete, name='process_file_delete'),
    path('<int:process_id>/file/latest/download/',
         views.process_file_download, name='process_file_download'),
    path('<int:process_id>/file/latest/preview/',
         views.process_file_preview, name='process_file_preview'),

    # === 공정별 약품 매핑 (AJAX) ===
    path('<int:process_id>/chemicals/search/',
         views.process_chemical_search, name='process_chemical_search'),
    path('<int:process_id>/chemicals/add/',
         views.process_chemical_add, name='process_chemical_add'),
    path('<int:process_id>/chemicals/<int:mapping_id>/delete/',
         views.process_chemical_delete, name='process_chemical_delete'),

    # === 공정별 설비 매핑 (AJAX) ===
    path('<int:process_id>/equipments/search/',
         views.process_equipment_search, name='process_equipment_search'),
    path('<int:process_id>/equipments/add/',
         views.process_equipment_add, name='process_equipment_add'),
    path('<int:process_id>/equipments/<int:mapping_id>/delete/',
         views.process_equipment_delete, name='process_equipment_delete'),

    # 공정별 비철 매핑
    path(
        "<int:process_id>/nonferrous/search/",
        views.process_nonferrous_search,
        name="process_nonferrous_search",
    ),
    path(
        "<int:process_id>/nonferrous/add/",
        views.process_nonferrous_add,
        name="process_nonferrous_add",
    ),
    path(
        "<int:process_id>/nonferrous/<int:mapping_id>/delete/",
        views.process_nonferrous_delete,
        name="process_nonferrous_delete",
    ),
]