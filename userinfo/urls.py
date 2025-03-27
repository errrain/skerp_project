from django.urls import path
from .views import user_form, user_result

app_name = 'userinfo'

urlpatterns = [
    path('form/', user_form, name='user_form'),
    path('result/<str:name>/<str:email>/', user_result, name='user_result'),
]