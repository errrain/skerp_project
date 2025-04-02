from django.urls import path
from . import views
from .views import user_edit

app_name = 'userinfo'

urlpatterns = [
    path('', views.user_list, name='user_list'),
    path('create/', views.user_create, name='user_create'),
    path('<int:user_id>/edit/', user_edit, name='user_edit') ,
    path('<int:pk>/delete/', views.user_delete, name='user_delete'),
]
