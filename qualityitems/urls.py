from django.urls import path
from . import views

app_name = 'qualityitems'

urlpatterns = [
    # 검사구분 (QualityGroup)
    path('group/', views.group_list, name='group_list'),
    path('group/add/', views.group_add, name='group_add'),
    path('group/<int:pk>/edit/', views.group_edit, name='group_edit'),
    path('group/<int:pk>/delete/', views.group_delete, name='group_delete'),

    # 검사항목 (QualityItem)
    path('item/', views.item_list, name='item_list'),
    path('item/add/', views.item_add, name='item_add'),
    path('item/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('item/<int:pk>/delete/', views.item_delete, name='item_delete'),
]
