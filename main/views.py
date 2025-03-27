from django.shortcuts import render
from django.http import HttpResponse
# Create your views here.

def index(request):
    content = {
        'username':' 서경화학',
        'age': '22',
        'hobby': ['3cr','유광','무광'],
    }
    return render(request, 'main/index.html',content)

def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        age = request.POST.get('age')
        context = {
            'username': username,
            'age': age,
        }
        return render(request, 'main/result.html', context)
    else:
        return render(request, 'main/form.html')