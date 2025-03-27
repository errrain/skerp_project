from django.urls import path

from . import views
from .views import post_list, post_create

app_name = 'board'

urlpatterns = [
    path('', post_list, name='post_list'),
    path('write/', post_create, name='post_create'),
    path('<int:post_id>/', views.post_detail, name='post_detail'),
    path('<int:post_id>/delete/', views.post_delete, name='post_delete'),
    path('<int:post_id>/edit/', views.post_edit, name='post_edit'),
]