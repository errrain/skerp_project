from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse_lazy

class CustomLoginView(LoginView):
    template_name = 'login_page.html'
    redirect_authenticated_user = True
    success_url = reverse_lazy('dashboard')

@login_required
def dashboard_view(request):
    return render(request, 'dashboard.html')