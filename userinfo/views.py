from django.shortcuts import render, get_object_or_404, redirect
from .models import CustomUser
from .forms import CustomUserForm

def user_list(request):
    users = CustomUser.objects.all()
    return render(request, 'userinfo/user_list.html', {'users': users})

def user_create(request):
    if request.method == 'POST':
        print("📩 POST 요청 도착")
        form = CustomUserForm(request.POST)
        if form.is_valid():
            print("✅ 유효성 통과")
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])  # ✅ 평문 password → 해시
            user.save()
            return redirect('userinfo:user_list')
        else:
            print("[❗유효성 오류]", form.errors)
    else:
        print("🌐 GET 요청: 빈 폼 렌더링")
        form = CustomUserForm()
    return render(request, 'userinfo/user_form.html', {'form': form})


def user_edit(request, user_id):
    user = get_object_or_404(CustomUser, pk=user_id)

    if request.method == 'POST':
        print("📩 POST 요청 도착 (수정)")
        form = CustomUserForm(request.POST, instance=user)
        if form.is_valid():
            print("✅ 유효성 통과 (수정)")
            user = form.save(commit=False)

            # 비밀번호 변경 여부 확인
            new_password = form.cleaned_data.get('password')
            if new_password:
                user.set_password(new_password)  # ✅ 변경된 비밀번호 해싱

            user.save()
            return redirect('userinfo:user_list')
        else:
            print("[❗유효성 오류]", form.errors)
    else:
        form = CustomUserForm(instance=user)

    return render(request, 'userinfo/user_form.html', {'form': form})

def user_delete(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    user.delete()
    return redirect('userinfo:user_list')
