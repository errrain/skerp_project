# mastercode/urls.py

from django.urls import path
from . import views

app_name = 'mastercode'

urlpatterns = [
    path('codegroups/', views.codegroup_list, name='codegroup_list'),
    path('codegroups/add/', views.codegroup_add, name='codegroup_add'),
    path('codegroups/<int:pk>/edit/', views.codegroup_edit, name='codegroup_edit'),
    path('codegroups/<int:pk>/delete/', views.codegroup_delete, name='codegroup_delete'),

    path('codedetails/', views.codedetail_list, name='codedetail_list'),
    path('codedetails/add/', views.codedetail_add, name='codedetail_add'),
    path('codedetails/<int:pk>/edit/', views.codedetail_edit, name='codedetail_edit'),
    path('codedetails/<int:pk>/delete/', views.codedetail_delete, name='codedetail_delete'),
    path('codedetails/bulk_add/', views.codedetail_bulk_add, name='codedetail_bulk_add'),
]
