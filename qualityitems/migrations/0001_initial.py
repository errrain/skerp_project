# Generated by Django 5.1.7 on 2025-04-03 08:43

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='QualityGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=10, unique=True, verbose_name='검사구분코드')),
                ('name', models.CharField(max_length=100, verbose_name='검사구분명')),
                ('use_yn', models.CharField(choices=[('Y', '사용'), ('N', '미사용')], default='Y', max_length=1, verbose_name='사용여부')),
                ('created_dt', models.DateTimeField(auto_now_add=True, verbose_name='생성일시')),
                ('updated_dt', models.DateTimeField(auto_now=True, verbose_name='수정일시')),
                ('created_by', models.CharField(blank=True, max_length=50, null=True, verbose_name='생성자')),
                ('updated_by', models.CharField(blank=True, max_length=50, null=True, verbose_name='수정자')),
            ],
        ),
        migrations.CreateModel(
            name='QualityItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, unique=True, verbose_name='검사항목코드')),
                ('name', models.CharField(max_length=100, verbose_name='검사항목명')),
                ('method', models.TextField(blank=True, verbose_name='검사방법')),
                ('upper_limit', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='허용 상한')),
                ('lower_limit', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='허용 하한')),
                ('use_yn', models.CharField(choices=[('Y', '사용'), ('N', '미사용')], default='Y', max_length=1, verbose_name='사용여부')),
                ('created_dt', models.DateTimeField(auto_now_add=True, verbose_name='생성일시')),
                ('updated_dt', models.DateTimeField(auto_now=True, verbose_name='수정일시')),
                ('created_by', models.CharField(blank=True, max_length=50, null=True, verbose_name='생성자')),
                ('updated_by', models.CharField(blank=True, max_length=50, null=True, verbose_name='수정자')),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='qualityitems.qualitygroup')),
            ],
        ),
    ]
