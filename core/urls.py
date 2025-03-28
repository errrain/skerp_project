from django.urls import path, reverse_lazy
from .views import CustomLoginView, dashboard_view
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('', CustomLoginView.as_view(), name='login'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('logout/', LogoutView.as_view(next_page=reverse_lazy('login')), name='logout'),
]