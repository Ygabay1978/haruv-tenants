import unittest,json
from unittest.mock import patch
import test_security as security
import server,notice_mail

class EmailOnlyTests(unittest.TestCase):
    setUp=security.IsolationTests.setUp
    tearDown=security.IsolationTests.tearDown
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    def admin(self):
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',))
        self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
        return self.session('owner@example.com')
    def data(self,**changes):
        return {'kind':'message','title':'Portal launch','body':'Full body <private>','apt':None,'audience':'all','active':1,'delivery':'email','attachments':[],**changes}
    def test_email_only_full_body_no_portal_and_no_duplicate_send(self):
        cookie=self.admin()
        with patch('server.send_notice_emails') as sender:
            r=self.request('/api/admin/notices',self.data(),cookie=cookie)
            self.assertTrue(r['status'].startswith('200'));saved=json.loads(r['body'])
            self.assertEqual(saved['notification']['state'],'accepted')
            self.assertEqual(set(sender.call_args.args[1]),{'owner@example.com','tenant@example.com','other@example.com'})
            self.assertTrue(sender.call_args.args[0]['email_only'])
            ident=saved['id']
            self.assertEqual(self.c.execute('SELECT active FROM notices WHERE id=?',(ident,)).fetchone()['active'],0)
            resident=json.loads(self.request('/api/apartments',cookie=self.session('tenant@example.com'))['body'])
            self.assertEqual(resident['apartments'][0]['notices'],[])
            again=self.request('/api/admin/notices',self.data(id=ident,version=1),cookie=cookie)
            self.assertEqual(json.loads(again['body'])['notification']['state'],'unchanged')
            notice_mail.deliver(self.c,ident,1,server.send_notice_emails)
            self.assertEqual(sender.call_count,1)
            admin=json.loads(self.request('/api/admin/notices',cookie=cookie)['body'])
            self.assertTrue(admin['notices'][0]['email_only'])
    def test_scope_permissions_drafts_and_invalid_mode(self):
        cookie=self.admin()
        self.assertTrue(self.request('/api/admin/notices',self.data(),cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/notices',self.data(delivery='bogus'),cookie=cookie)['status'].startswith('400'))
        with patch('server.send_notice_emails') as sender:
            self.request('/api/admin/notices',self.data(delivery='draft'),cookie=cookie);sender.assert_not_called()
            self.request('/api/admin/notices',self.data(apt=1,audience='tenant'),cookie=cookie)
            self.assertEqual(sender.call_args.args[1],['tenant@example.com'])
    def test_email_template_contains_full_body_and_link(self):
        class Response:
            status=201
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('server.urlopen',return_value=Response()) as send:
            server.send_notice_emails({'title':'Hello','body':'Full body <private>','email_only':True},['tenant@example.com'],'id')
            payload=json.loads(send.call_args.args[0].data)
            self.assertIn('Full body <private>',payload['textContent'])
            self.assertIn('&lt;private&gt;',payload['htmlContent'])
            self.assertNotIn('מחכה לך',payload['textContent'])
            self.assertIn(server.ORIGIN,payload['textContent'])
    def test_rtl_for_otp_and_both_notice_modes(self):
        class Response:
            status=201
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('server.urlopen',return_value=Response()) as send:
            server.send_email('owner@example.com','012345')
            otp=json.loads(send.call_args.args[0].data)
            self.assertIn('dir="rtl"',otp['htmlContent'])
            self.assertIn('align="right"',otp['htmlContent'])
            self.assertIn('dir="ltr"',otp['htmlContent'])
            self.assertIn('012345',otp['htmlContent'])
            for mode in (False,True):
                server.send_notice_emails({'title':'שלום','body':'תוכן ההודעה','email_only':mode},['owner@example.com'],'key')
                data=json.loads(send.call_args.args[0].data)
                self.assertIn('align="right"',data['htmlContent'])
                self.assertIn('text-align:right',data['htmlContent'])
                self.assertTrue(data['textContent'].startswith('\u200f'))
