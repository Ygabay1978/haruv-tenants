import unittest,json,io
from datetime import datetime
import test_security as security
import portal_rules,tenant_summary

class ResidentFeatureTests(unittest.TestCase):
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    tearDown=security.IsolationTests.tearDown
    def setUp(self):
        security.IsolationTests.setUp(self)
        with self.c:
            for table in ('notices','administrators'):self.c.execute('DELETE FROM '+table)
    def test_public_help_exposes_only_designated_contact_fields(self):
        payload={'ownerContacts':[{'name':'Private Owner','email':'private@example.com'}], 'support':[{'name':'Committee Contact','phone':'0500000000','topics':'Maintenance','email':'hidden@example.com'}]}
        self.c.execute('UPDATE apartments SET payload=? WHERE apt=1',(json.dumps(payload),));self.c.commit()
        result=self.request('/api/support')
        self.assertTrue(result['status'].startswith('200'))
        self.assertEqual(json.loads(result['body']),{'contacts':[{'name':'Committee Contact','phone':'0500000000','topics':'Maintenance'}]})
        self.assertNotIn(b'private@example.com',result['body']);self.assertNotIn(b'hidden@example.com',result['body'])
    def test_preview_requires_explicit_viewer_and_remains_read_only(self):
        cookie=self.session('owner@example.com')
        self.assertTrue(self.request('/api/viewer/context',cookie=cookie)['status'].startswith('403'))
        self.assertTrue(self.request('/api/preview',{'apt':2,'role':'owner'},cookie=cookie)['status'].startswith('403'))
        self.c.execute('INSERT INTO resident_viewers VALUES(?,1)',('owner@example.com',));self.c.commit()
        context=json.loads(self.request('/api/viewer/context',cookie=cookie)['body']);self.assertEqual(len(context['apartments']),2)
        preview=self.request('/api/preview',{'apt':2,'role':'owner'},cookie=cookie)
        self.assertIn(b'Private Other Owner',preview['body'])
        ordinary=json.loads(self.request('/api/apartments',cookie=cookie)['body']);self.assertEqual([a['apt'] for a in ordinary['apartments']],[1])
        self.assertTrue(self.request('/api/admin/context',cookie=cookie)['status'].startswith('403'))
        self.assertTrue(self.request('/api/preview',{'apt':2,'role':'invalid'},cookie=cookie)['status'].startswith('400'))
        self.assertTrue(self.request('/api/preview',{'apt':999,'role':'owner'},cookie=cookie)['status'].startswith('404'))
        self.c.execute('UPDATE resident_viewers SET active=0');self.c.commit()
        self.assertTrue(self.request('/api/preview',{'apt':2,'role':'owner'},cookie=cookie)['status'].startswith('403'))
    def test_preview_filters_notices_by_apartment_and_selected_role(self):
        self.make_admin();self.save(apt=1,audience='tenant',body='Tenant specific');self.save(apt=1,audience='owner',body='Owner specific');self.save(apt=2,body='Other apartment')
        owner=self.request('/api/preview',{'apt':1,'role':'owner'},cookie=self.session('owner@example.com'))
        tenant=self.request('/api/preview',{'apt':1,'role':'tenant'},cookie=self.session('owner@example.com'))
        self.assertIn(b'Owner specific',owner['body']);self.assertNotIn(b'Tenant specific',owner['body']);self.assertNotIn(b'Other apartment',owner['body'])
        self.assertIn(b'Tenant specific',tenant['body']);self.assertNotIn(b'Owner specific',tenant['body'])
    def make_admin(self):
        self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
    def save(self,**kw):
        body={'title':'Notice','body':'Private targeted text','kind':'message','audience':'all','active':1};body.update(kw)
        return self.request('/api/admin/notices',body,cookie=self.session('owner@example.com'))
    def test_resident_cannot_manage_notices(self):
        r=self.save();self.assertTrue(r['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/context',cookie=self.session('tenant@example.com'))['status'].startswith('403'))
    def test_targeted_owner_tenant_and_apartment_scoping(self):
        self.make_admin();self.assertTrue(self.save(apt=1,audience='tenant')['status'].startswith('200'))
        owner=self.request('/api/apartments',cookie=self.session('owner@example.com'))
        tenant=self.request('/api/apartments',cookie=self.session('tenant@example.com'))
        other=self.request('/api/apartments',cookie=self.session('other@example.com'))
        self.assertNotIn(b'Private targeted text',owner['body']);self.assertIn(b'Private targeted text',tenant['body']);self.assertNotIn(b'Private targeted text',other['body'])
        self.save(audience='owner',body='Owners announcement')
        self.assertIn(b'Owners announcement',self.request('/api/apartments',cookie=self.session('other@example.com'))['body'])
        self.assertNotIn(b'Owners announcement',self.request('/api/apartments',cookie=self.session('tenant@example.com'))['body'])
    def test_edit_conflict_archive_and_admin_revocation(self):
        self.make_admin();saved=json.loads(self.save(apt=1)['body']);row=dict(self.c.execute('SELECT * FROM notices WHERE id=?',(saved['id'],)).fetchone())
        row.update(body='Updated text',active=0)
        self.assertTrue(self.request('/api/admin/notices',row,cookie=self.session('owner@example.com'))['status'].startswith('200'))
        self.assertTrue(self.request('/api/admin/notices',row,cookie=self.session('owner@example.com'))['status'].startswith('409'))
        self.assertNotIn(b'Updated text',self.request('/api/apartments',cookie=self.session('tenant@example.com'))['body'])
        self.c.execute('UPDATE administrators SET active=0');self.c.commit()
        self.assertTrue(self.request('/api/admin/notices',cookie=self.session('owner@example.com'))['status'].startswith('403'))
    def test_notice_cannot_target_nonexistent_apartment(self):
        self.make_admin();self.assertTrue(self.save(apt=999)['status'].startswith('400'))

class SummaryAndDebtTests(unittest.TestCase):
    def test_bank_balance_and_private_fields_removed_from_response(self):
        data={'annualIncome':1000,'monthlyIncome':[100],'monthlyExpenses':[20],'months':['Month'],'fixedCosts':[], 'finalBalance':986543.21,'monthlyBalance':[987654.32]}
        html='<script id="embedded-summary" type="application/json">'+json.dumps(data)+'</script><script id="embedded-bank">{"secret_bank":123987.45}</script>'
        result=tenant_summary.render(html)
        for key in ('986543.21','987654.32','123987.45','embedded-bank','finalBalance','monthlyBalance','secret_bank'):self.assertNotIn(key,result)
        self.assertIn('annualIncome',result)
    def test_future_months_do_not_trigger_collection_warning(self):
        data={'monthly':100,'due':200,'monthlyPayments':[100]*10+[0,0]}
        self.assertIsNone(portal_rules.collection_status(data,datetime(2026,10,22))['level'])
    def test_warning_thresholds_and_annual_due_cap(self):
        data={'monthly':100,'due':1200,'monthlyPayments':[100]*7+[0]*5}
        self.assertEqual(portal_rules.collection_status(data,datetime(2026,10,22))['level'],'payment')
        data['monthlyPayments']=[100]*6+[0]*6
        self.assertEqual(portal_rules.collection_status(data,datetime(2026,10,22))['level'],'legal')
        data['due']=0
        self.assertIsNone(portal_rules.collection_status(data,datetime(2026,10,22))['level'])
