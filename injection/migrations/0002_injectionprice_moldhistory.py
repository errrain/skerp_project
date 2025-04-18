# Generated by Django 5.1.7 on 2025-04-03 16:41

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('injection', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InjectionPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='일자')),
                ('price', models.PositiveIntegerField(verbose_name='단가')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='등록자')),
                ('injection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='prices', to='injection.injection', verbose_name='사출품')),
            ],
            options={
                'ordering': ['-date'],
            },
        ),
        migrations.CreateModel(
            name='MoldHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('history_date', models.DateField(verbose_name='이력일자')),
                ('content', models.TextField(blank=True, null=True, verbose_name='이력 내용')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='등록자')),
                ('injection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mold_histories', to='injection.injection', verbose_name='사출품')),
            ],
            options={
                'verbose_name': '금형 이력',
                'verbose_name_plural': '금형 이력 목록',
                'ordering': ['-history_date'],
            },
        ),
    ]
