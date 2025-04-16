# Generated by Django 5.2 on 2025-04-15 16:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('injection', '0004_injectionprice'),
    ]

    operations = [
        migrations.CreateModel(
            name='MoldHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('history_date', models.DateField(verbose_name='이력일자')),
                ('content', models.TextField(verbose_name='내용')),
                ('created_by', models.CharField(max_length=50, verbose_name='등록자')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='등록일시')),
                ('injection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='molds', to='injection.injection', verbose_name='사출품')),
            ],
            options={
                'ordering': ['-history_date'],
            },
        ),
    ]
