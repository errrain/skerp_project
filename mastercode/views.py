# mastercode/views.py
from django.forms import modelformset_factory
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .models import CodeGroup, CodeDetail
from .forms import CodeGroupForm, CodeDetailForm
from django.core.paginator import Paginator


def codegroup_list(request):
    queryset = CodeGroup.objects.all()
    group_code = request.GET.get('group_code', '')
    group_name = request.GET.get('group_name', '')
    page_size = request.GET.get('page_size', 10)

    if group_code:
        queryset = queryset.filter(group_code__icontains=group_code)
    if group_name:
        queryset = queryset.filter(group_name__icontains=group_name)

    try:
        page_size = int(page_size)
    except ValueError:
        page_size = 10

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'groups': page_obj,
        'page_obj': page_obj,
        'group_code': group_code,
        'group_name': group_name,
        'page_size': page_size,
    }
    return render(request, 'mastercode/codegroup_list.html', context)


def codegroup_add(request):
    if request.method == 'POST':
        form = CodeGroupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('mastercode:codegroup_list')
    else:
        form = CodeGroupForm()
    return render(request, 'mastercode/codegroup_form.html', {'form': form})


def codegroup_edit(request, pk):
    group = get_object_or_404(CodeGroup, pk=pk)
    if request.method == 'POST':
        form = CodeGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            return redirect('mastercode:codegroup_list')
    else:
        form = CodeGroupForm(instance=group)
    return render(request, 'mastercode/codegroup_form.html', {'form': form})


def codegroup_delete(request, pk):
    group = get_object_or_404(CodeGroup, pk=pk)
    group.delete()
    return redirect('mastercode:codegroup_list')


def codedetail_list(request):
    queryset = CodeDetail.objects.select_related('group').all()
    code = request.GET.get('code', '')
    name = request.GET.get('name', '')
    group_id = request.GET.get('group', '')
    page_size = request.GET.get('page_size', 10)

    selected_group = None
    if group_id:
        queryset = queryset.filter(group__id=group_id)
        selected_group = CodeGroup.objects.filter(id=group_id).first()

    if code:
        queryset = queryset.filter(code__icontains=code)
    if name:
        queryset = queryset.filter(name__icontains=name)

    try:
        page_size = int(page_size)
    except ValueError:
        page_size = 10

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'details': page_obj,
        'page_obj': page_obj,
        'code': code,
        'name': name,
        'group_id': group_id,
        'page_size': page_size,
        'groups': CodeGroup.objects.all(),
        'selected_group': selected_group,
    }
    return render(request, 'mastercode/codedetail_list.html', context)




def codedetail_add(request):
    group_id = request.GET.get('group')  # ← URL 파라미터로부터 group 추출
    initial_data = {}

    if group_id:
        initial_data['group'] = group_id  # 초기값 지정

    if request.method == 'POST':
        form = CodeDetailForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('mastercode:codedetail_list')
    else:
        form = CodeDetailForm(initial=initial_data)

    return render(request, 'mastercode/codedetail_form.html', {'form': form})


def codedetail_edit(request, pk):
    detail = get_object_or_404(CodeDetail, pk=pk)
    if request.method == 'POST':
        form = CodeDetailForm(request.POST, instance=detail)
        if form.is_valid():
            form.save()
            return redirect('mastercode:codedetail_list')
    else:
        form = CodeDetailForm(instance=detail)
    return render(request, 'mastercode/codedetail_form.html', {'form': form})


def codedetail_delete(request, pk):
    detail = get_object_or_404(CodeDetail, pk=pk)
    detail.delete()
    return redirect('mastercode:codedetail_list')


CodeDetailFormSet = modelformset_factory(CodeDetail, fields=('group', 'code', 'name', 'sort_order', 'is_active'), extra=5)

def codedetail_bulk_add(request):
    group_id = request.GET.get('group')
    initial = [{'group': group_id}] * 5 if group_id else [{}] * 5
    formset = CodeDetailFormSet(request.POST or None, queryset=CodeDetail.objects.none(), initial=initial)

    if request.method == 'POST' and formset.is_valid():
        formset.save()
        # ✅ 저장 후 등록된 그룹으로 리다이렉트
        redirect_url = reverse('mastercode:codedetail_list')
        if group_id:
            redirect_url += f'?group={group_id}'
        return redirect(redirect_url)

    return render(request, 'mastercode/codedetail_bulk_form.html', {
        'formset': formset,
        'group_id': group_id,
    })