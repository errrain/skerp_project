from django.test import TestCase

from mastercode.models import CodeGroup, CodeDetail
from userinfo.forms import CustomUserForm
from vendor.models import Vendor


class CustomUserFormDepartmentCodeTests(TestCase):
    def setUp(self):
        self.group = CodeGroup.objects.create(group_code='DEPARTMENT', group_name='부서')
        CodeDetail.objects.create(group=self.group, code='SALES', name='영업', sort_order=1, is_active=True)
        self.vendor = Vendor.objects.create(
            vendor_type='corporate',
            name='테스트거래처',
            biz_number='123-45-67890',
            transaction_type='buy',
            outsourcing_type='PT',
            status='active',
            can_login=True,
        )

    def _base_data(self, **overrides):
        data = {
            'username': 'tester',
            'password': 'pass1234!',
            'full_name': '테스터',
            'department': 'SALES',
            'level': 'user',
            'status': 'active',
            'phone': '010-0000-0000',
            'email': 'tester@example.com',
            'is_internal': '',
            'vendor': str(self.vendor.pk),
        }
        data.update(overrides)
        return data

    def test_department_is_loaded_from_mastercode_group(self):
        form = CustomUserForm()
        self.assertIn(('SALES', '영업'), form.fields['department'].choices)

    def test_invalid_department_code_is_rejected(self):
        form = CustomUserForm(data=self._base_data(department='INVALID'))
        self.assertFalse(form.is_valid())
        self.assertIn('department', form.errors)

    def test_external_user_requires_vendor(self):
        form = CustomUserForm(data=self._base_data(vendor=''))
        self.assertFalse(form.is_valid())
        self.assertIn('vendor', form.errors)
