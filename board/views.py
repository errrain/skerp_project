from django.shortcuts import render, redirect
from django.urls import reverse
from .models import Post

def post_list(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'board/post_list.html', {'posts': posts})

def post_create(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        post = Post.objects.create(title=title, content=content)
        return redirect('board:post_detail', post_id=post.id)

    return render(request, 'board/post_form.html', {
        'form_title': '글 작성',
        'button_text': '등록',
        'post': None,
    })

def post_detail(request, post_id):
    post = Post.objects.get(id=post_id)
    return render(request, 'board/post_detail.html', {'post': post})

def post_delete(request, post_id):
    post = Post.objects.get(id=post_id)
    post.delete()
    return redirect('board:post_list')

def post_edit(request, post_id):
    post = Post.objects.get(id=post_id)

    if request.method == 'POST':
        post.title = request.POST.get('title')
        post.content = request.POST.get('content')
        post.save()
        return redirect('board:post_detail', post_id=post.id)

    return render(request, 'board/post_form.html', {
        'form_title': '글 수정',
        'button_text': '수정',
        'post': post,
    })
