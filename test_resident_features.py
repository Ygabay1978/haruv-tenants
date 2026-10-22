import unittest,json,io
from unittest.mock import patch
from datetime import datetime
import test_security as security
import portal_rules,tenant_summary

class ResidentFeatureTests(unittest.TestCase):
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    tearDown=security.IsolationTests.tearDown
    def setUp(self):
        security.IsolationTests.setUp(self)
        self.mail_patch=patch('server.send_notice_emails');self.mailer=self.mail_patch.start();self.addCleanup(self.mail_patch.stop)
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
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',));self.c.execute('INSERT INTO resident_viewers VALUES(?,1)',('owner@example.com',));self.c.commit()
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
    def test_dashboard_token_is_owner_bound_origin_bound_scoped_and_logout_revoked(self):
        import server
        self.make_admin();cookie=self.session('owner@example.com')
        issued=self.request('/api/admin/dashboard-session',{},cookie=cookie);token=json.loads(issued['body'])['token'];authorization='Bearer '+token
        allowed=self.request('/api/admin/context',origin=server.DASHBOARD_ORIGIN,authorization=authorization)
        self.assertTrue(allowed['status'].startswith('200'));self.assertEqual(allowed['headers']['Access-Control-Allow-Origin'],server.DASHBOARD_ORIGIN)
        self.assertNotIn('Access-Control-Allow-Credentials',allowed['headers'])
        for path in ('/api/apartments','/api/preview','/api/admin/dashboard-session'):
            self.assertTrue(self.request(path,{},origin=server.DASHBOARD_ORIGIN,authorization=authorization)['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/context',authorization=authorization)['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/context',origin=server.DASHBOARD_ORIGIN,cookie=cookie)['status'].startswith('403'))
        self.request('/api/logout',{},cookie=cookie)
        self.assertTrue(self.request('/api/admin/context',origin=server.DASHBOARD_ORIGIN,authorization=authorization)['status'].startswith('401'))
    def test_dashboard_token_cannot_be_issued_to_another_resident(self):
        self.assertTrue(self.request('/api/admin/dashboard-session',{},cookie=self.session('other@example.com'))['status'].startswith('403'))
        import server
        self.assertTrue(self.request('/api/admin/context',method='OPTIONS',origin=server.DASHBOARD_ORIGIN)['status'].startswith('200'))
        self.assertTrue(self.request('/api/admin/context',method='OPTIONS',origin='https://untrusted.example')['status'].startswith('403'))
        self.assertTrue(self.request('/api/send-code',{'email':'owner@example.com'},origin=server.DASHBOARD_ORIGIN)['status'].startswith('403'))
    def test_committee_view_sees_both_role_notices_but_only_selected_apartment(self):
        self.make_admin();self.save(apt=1,audience='owner',body='Owner notice');self.save(apt=1,audience='tenant',body='Tenant notice');self.save(apt=2,body='Other unit notice')
        result=self.request('/api/preview',{'apt':1,'role':'committee'},cookie=self.session('owner@example.com'))
        self.assertIn(b'Owner notice',result['body']);self.assertIn(b'Tenant notice',result['body']);self.assertNotIn(b'Other unit notice',result['body'])
        self.assertTrue(self.request('/api/preview',{'apt':1,'role':'committee'},cookie=self.session('other@example.com'))['status'].startswith('403'))
    def test_delete_hides_notice_and_restore_is_draft_without_email(self):
        self.make_admin();saved=json.loads(self.save(apt=1)['body']);calls=self.mailer.call_count
        cookie=self.session('owner@example.com');payload={'id':saved['id'],'version':1}
        self.assertTrue(self.request('/api/admin/notices/delete',payload,cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/notices/delete',payload,cookie=cookie)['status'].startswith('200'))
        self.assertNotIn(b'Private targeted text',self.request('/api/apartments',cookie=self.session('tenant@example.com'))['body'])
        self.assertEqual(json.loads(self.request('/api/admin/notices',cookie=cookie)['body'])['notices'],[])
        archived=json.loads(self.request('/api/admin/notices/deleted',cookie=cookie)['body'])['notices'][0]
        self.assertTrue(self.request('/api/admin/notices/restore',{'id':archived['id'],'version':archived['version']},cookie=cookie)['status'].startswith('200'))
        row=self.c.execute('SELECT active FROM notices WHERE id=?',(saved['id'],)).fetchone();self.assertEqual(row['active'],0);self.assertEqual(self.mailer.call_count,calls)
    def test_attachments_require_exact_notice_apartment_role_and_active_membership(self):
        import base64
        self.make_admin();cookie=self.session('owner@example.com')
        data={'filename':'example.pdf','data':base64.b64encode(b'%PDF-1.4\nexample').decode()}
        uploaded=self.request('/api/admin/attachments/upload',data,cookie=cookie);attachment=json.loads(uploaded['body']);self.assertIn('id',attachment)
        body={'apt':1,'audience':'owner','kind':'message','title':'With file','body':'Attachment body','active':1,'attachments':[attachment['id']]}
        saved=self.request('/api/admin/notices',body,cookie=cookie);self.assertTrue(saved['status'].startswith('200'))
        path='/api/attachments/'+attachment['id']
        self.assertTrue(self.request(path,cookie=cookie)['status'].startswith('200'))
        self.assertTrue(self.request(path,cookie=self.session('tenant@example.com'))['status'].startswith('404'))
        self.assertTrue(self.request(path,cookie=self.session('other@example.com'))['status'].startswith('404'))
        notice=dict(self.c.execute('SELECT * FROM notices WHERE id=?',(json.loads(saved['body'])['id'],)).fetchone());notice['audience']='all';notice['attachments']=[attachment['id']]
        self.request('/api/admin/notices',notice,cookie=cookie)
        self.assertTrue(self.request(path,cookie=self.session('tenant@example.com'))['status'].startswith('200'))
        self.assertTrue(self.request(path,cookie=self.session('other@example.com'))['status'].startswith('404'))
        self.c.execute("UPDATE email_memberships SET active=0 WHERE email='tenant@example.com'");self.c.commit()
        self.assertTrue(self.request(path,cookie=self.session('tenant@example.com'))['status'].startswith('401'))
    def test_global_attachment_archive_and_rebinding_guards(self):
        import base64,server
        self.make_admin();cookie=self.session('owner@example.com')
        item=json.loads(self.request('/api/admin/attachments/upload',{'filename':'safe.txt','data':base64.b64encode(b'Example file').decode()},cookie=cookie)['body'])
        notice=json.loads(self.save(attachments=[item['id']])['body']);path='/api/attachments/'+item['id']
        self.assertTrue(self.request(path,cookie=self.session('other@example.com'))['status'].startswith('200'))
        self.assertTrue(self.save(attachments=[item['id']])['status'].startswith('400'))
        self.assertTrue(self.save(attachments=[{}])['status'].startswith('400'))
        token=json.loads(self.request('/api/admin/dashboard-session',{},cookie=cookie)['body'])['token']
        download=self.request('/api/admin/attachments/'+item['id'],origin=server.DASHBOARD_ORIGIN,authorization='Bearer '+token)
        self.assertEqual(download['body'],b'Example file')
        self.request('/api/admin/notices/delete',{'id':notice['id'],'version':1},cookie=cookie)
        self.assertTrue(self.request(path,cookie=self.session('other@example.com'))['status'].startswith('404'))

    def test_unsafe_attachment_types_and_resident_upload_are_rejected(self):
        import base64
        self.make_admin();data={'filename':'bad.html','data':base64.b64encode(b'<html>active content</html>').decode()}
        self.assertTrue(self.request('/api/admin/attachments/upload',data,cookie=self.session('owner@example.com'))['status'].startswith('400'))
        data['filename']='bad.png';self.assertTrue(self.request('/api/admin/attachments/upload',data,cookie=self.session('owner@example.com'))['status'].startswith('400'))
        self.assertTrue(self.request('/api/admin/attachments/upload',data,cookie=self.session('tenant@example.com'))['status'].startswith('403'))
    def make_admin(self):
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',));self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
    def save(self,**kw):
        body={'title':'Notice','body':'Private targeted text','kind':'message','audience':'all','active':1};body.update(kw)
        return self.request('/api/admin/notices',body,cookie=self.session('owner@example.com'))
    def test_other_admin_or_viewer_row_cannot_override_single_committee_identity(self):
        self.make_admin()
        self.c.execute('INSERT INTO administrators VALUES(?,1)',('other@example.com',));self.c.execute('INSERT INTO resident_viewers VALUES(?,1)',('other@example.com',));self.c.commit()
        other=self.session('other@example.com')
        for path in ('/api/admin/context','/api/viewer/context','/api/admin/notices'):
            self.assertTrue(self.request(path,cookie=other)['status'].startswith('403'))
        self.assertTrue(self.request('/api/preview',{'apt':1,'role':'owner'},cookie=other)['status'].startswith('403'))
    def test_notification_targets_active_selected_role_and_deduplicates(self):
        self.make_admin()
        self.c.execute('INSERT INTO email_memberships VALUES(?,?,?,1)',('owner@example.com',1,'tenant'))
        self.c.execute('INSERT INTO email_memberships VALUES(?,?,?,0)',('former@example.com',1,'tenant'));self.c.commit()
        self.save(apt=1,audience='tenant')
        self.assertEqual(self.mailer.call_args.args[1],['owner@example.com','tenant@example.com'])
        self.assertNotIn('other@example.com',self.mailer.call_args.args[1])
        self.mailer.reset_mock();self.save(apt=1,audience='owner')
        self.assertEqual(self.mailer.call_args.args[1],['owner@example.com'])
    def test_hidden_and_unchanged_notices_do_not_email(self):
        self.make_admin();saved=json.loads(self.save(apt=1,active=0)['body']);self.mailer.assert_not_called()
        row=dict(self.c.execute('SELECT * FROM notices WHERE id=?',(saved['id'],)).fetchone());row['active']=1
        self.request('/api/admin/notices',row,cookie=self.session('owner@example.com'));self.assertEqual(self.mailer.call_count,1)
        row=dict(self.c.execute('SELECT * FROM notices WHERE id=?',(saved['id'],)).fetchone());self.request('/api/admin/notices',row,cookie=self.session('owner@example.com'));self.assertEqual(self.mailer.call_count,1)
    def test_failed_email_is_visible_and_retries_without_duplicate_after_acceptance(self):
        import notice_mail
        self.make_admin();self.mailer.side_effect=notice_mail.Rejected()
        saved=json.loads(self.save(apt=1)['body']);self.assertEqual(saved['notification']['state'],'failed')
        self.assertEqual(self.c.execute('SELECT active FROM notices WHERE id=?',(saved['id'],)).fetchone()['active'],1)
        self.mailer.side_effect=None
        request={'id':saved['id'],'version':1}
        result=self.request('/api/admin/notifications/retry',request,cookie=self.session('owner@example.com'))
        self.assertEqual(json.loads(result['body'])['notification']['state'],'accepted');count=self.mailer.call_count
        self.request('/api/admin/notifications/retry',request,cookie=self.session('owner@example.com'));self.assertEqual(self.mailer.call_count,count)
    def test_uncertain_email_is_not_automatically_resent(self):
        self.make_admin();self.mailer.side_effect=TimeoutError()
        saved=json.loads(self.save(apt=1)['body']);self.assertEqual(saved['notification']['state'],'unknown')
        self.request('/api/admin/notifications/retry',{'id':saved['id'],'version':1},cookie=self.session('owner@example.com'));self.assertEqual(self.mailer.call_count,1)
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

class NotificationPayloadTests(unittest.TestCase):
    def test_provider_payload_has_private_recipient_versions_title_and_login_link(self):
        import server,os
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value.status=201
        settings={'BREVO_API_KEY':'test-only','EMAIL_FROM':'board@example.com','OTP_SECRET':'x'*40}
        with patch.dict(os.environ,settings),patch.object(server,'ORIGIN','https://portal.test'),patch('server.urlopen',return_value=response) as send:
            server.send_notice_emails({'title':'מים <פרטי>','body':'DO NOT EMAIL THIS BODY'},['one@example.com','two@example.com'],'d3ed8497-1931-5197-b6ac-4f3c089ec173')
        payload=json.loads(send.call_args.args[0].data)
        self.assertNotIn('to',payload);self.assertEqual([len(v['to']) for v in payload['messageVersions']],[1,1])
        self.assertIn('https://portal.test/',payload['htmlContent']);self.assertIn('מים &lt;פרטי&gt;',payload['htmlContent']);self.assertNotIn('DO NOT EMAIL THIS BODY',json.dumps(payload))
        self.assertEqual(payload['headers']['idempotencyKey'],'d3ed8497-1931-5197-b6ac-4f3c089ec173')
