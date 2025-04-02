# master/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import CompanyInfo, Warehouse
from .forms import CompanyInfoForm, WarehouseForm


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

# 📄 목록 조회
def warehouse_list(request):
    warehouses = Warehouse.objects.filter(is_deleted='N').order_by('warehouse_id')
    return render(request, 'master/warehouse_list.html', {'warehouses': warehouses})


# ➕ 신규 등록


def warehouse_create(request):
    if request.method == 'POST':
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save(commit=False)
            warehouse.save()
            warehouse.warehouse_id = f"sk_wh_{warehouse.pk}"
            warehouse.save()
            return redirect('master:warehouse_list')
        else:
            print("[❗유효성 오류]", form.errors)
    else:
        form = WarehouseForm()
    return render(request, 'master/warehouse_form.html', {'form': form})


# 🛠 수정
def warehouse_edit(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == 'POST':
        form = WarehouseForm(request.POST, instance=warehouse)
        if form.is_valid():
            updated_warehouse = form.save(commit=False)
            updated_warehouse.warehouse_id = warehouse.warehouse_id  # 유지
            updated_warehouse.save()
            return redirect('master:warehouse_list')
    else:
        form = WarehouseForm(instance=warehouse)
    return render(request, 'master/warehouse_form.html', {'form': form})


# ❌ 삭제
def warehouse_delete(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    warehouse.is_deleted = 'Y'
    warehouse.save()
    return redirect('master:warehouse_list')
