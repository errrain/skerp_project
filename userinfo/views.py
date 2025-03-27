from django.shortcuts import render, redirect
from django.urls import reverse

def user_form(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        # 여기서 데이터를 처리하거나 저장할 수 있습니다.
        return redirect(reverse('userinfo:user_result', kwargs={'name': name, 'email': email}))
    return render(request, 'userinfo/user_form.html')

def user_result(request, name, email):
    context = {'name': name, 'email': email}
    return render(request, 'userinfo/user_result.html', context)