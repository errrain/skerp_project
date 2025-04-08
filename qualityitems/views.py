from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from .models import QualityGroup, QualityItem
from .forms import QualityGroupForm, QualityItemForm


### 📌 검사구분 리스트
def group_list(request):
    name = request.GET.get('name', '')
    use_yn = request.GET.get('use_yn', '')
    groups = QualityGroup.objects.all()
    if name:
        groups = groups.filter(name__icontains=name)
    if use_yn:
        groups = groups.filter(use_yn=use_yn)

    paginator = Paginator(groups, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'qualityitems/group_list.html', {
        'page_obj': page_obj,
        'name': name,
        'use_yn': use_yn,
    })


### 📌 검사구분 등록
def group_add(request):
    if request.method == 'POST':
        form = QualityGroupForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.created_by = request.user.username
            group.save()
            return redirect('qualityitems:group_list')
    else:
        form = QualityGroupForm()
    return render(request, 'qualityitems/group_form.html', {'form': form})


### 📌 검사구분 수정
def group_edit(request, pk):
    group = get_object_or_404(QualityGroup, pk=pk)
    if request.method == 'POST':
        form = QualityGroupForm(request.POST, instance=group)
        if form.is_valid():
            group = form.save(commit=False)
            group.updated_by = request.user.username
            group.save()
            return redirect('qualityitems:group_list')
    else:
        form = QualityGroupForm(instance=group)
    return render(request, 'qualityitems/group_form.html', {'form': form})


### 📌 검사구분 삭제
def group_delete(request, pk):
    group = get_object_or_404(QualityGroup, pk=pk)
    group.delete()
    return redirect('qualityitems:group_list')


### 📌 검사항목 리스트
def item_list(request):
    group_id = request.GET.get('group', '')
    name = request.GET.get('name', '')
    use_yn = request.GET.get('use_yn', '')
    items = QualityItem.objects.select_related('group').all()

    if group_id:
        items = items.filter(group_id=group_id)
    if name:
        items = items.filter(name__icontains=name)
    if use_yn:
        items = items.filter(use_yn=use_yn)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    groups = QualityGroup.objects.filter(use_yn='Y')

    return render(request, 'qualityitems/item_list.html', {
        'page_obj': page_obj,
        'group_id': group_id,
        'name': name,
        'use_yn': use_yn,
        'groups': groups,
    })


### 📌 검사항목 등록
def item_add(request):
    group_id = request.GET.get('group')
    initial_data = {'group': group_id} if group_id else {}

    if request.method == 'POST':
        form = QualityItemForm(request.POST)
        if form.is_valid():
            form.save(user=request.user)
            return redirect('qualityitems:item_list')
    else:
        form = QualityItemForm(initial=initial_data)

    return render(request, 'qualityitems/item_form.html', {'form': form})


### 📌 검사항목 수정
def item_edit(request, pk):
    item = get_object_or_404(QualityItem, pk=pk)
    if request.method == 'POST':
        form = QualityItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save(user=request.user)
            return redirect('qualityitems:item_list')
    else:
        form = QualityItemForm(instance=item)
    return render(request, 'qualityitems/item_form.html', {'form': form})


### 📌 검사항목 삭제
def item_delete(request, pk):
    item = get_object_or_404(QualityItem, pk=pk)
    item.delete()
    return redirect('qualityitems:item_list')
