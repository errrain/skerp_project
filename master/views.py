# master/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import CompanyInfo
from .forms import CompanyInfoForm

def company_list(request):
    companies = CompanyInfo.objects.all()
    return render(request, 'master/company_list.html', {'companies': companies})

def company_create(request):
    if request.method == 'POST':
        form = CompanyInfoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('master:company_list')
    else:
        form = CompanyInfoForm()
    return render(request, 'master/company_form.html', {'form': form})

def company_edit(request, pk):
    company = get_object_or_404(CompanyInfo, pk=pk)
    if request.method == 'POST':
        form = CompanyInfoForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            return redirect('master:company_list')
    else:
        form = CompanyInfoForm(instance=company)
    return render(request, 'master/company_form.html', {'form': form})

def company_delete(request, pk):
    company = get_object_or_404(CompanyInfo, pk=pk)
    company.delete()
    return redirect('master:company_list')
