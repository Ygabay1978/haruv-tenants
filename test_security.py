import unittest,tempfile,io,json,time,hashlib,os,secrets
from pathlib import Path
from unittest.mock import patch
import server

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.env_patch=patch.dict(os.environ, {'DATABASE_URL':os.environ.get('TEST_DATABASE_URL',''),'PORTAL_TEST_DATABASE':'1','BREVO_API_KEY':'test','EMAIL_FROM':'board@example.com','OTP_SECRET':'x'*40})
        self.env_patch.start()
        self.temp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=str(Path(self.temp.name)/'db');server.ORIGIN='https://portal.test'
        self.c=server.connect()
        with self.c:
            for table in ['committee_account','notice_notifications','resident_viewers','notices','administrators','presentation','email_challenges','email_sessions','memberships','sessions','attempts','email_memberships','apartments','summary']: self.c.execute('DELETE FROM '+table)
        self.c.executemany('INSERT INTO apartments VALUES(?,?)',[(1,'{"paid":100,"owners":["Owner One"],"tenants":["Tenant One"],"access":{"gym":"Gym One","pal":"PAL One"}}'),(2,'{"paid":98765,"owners":["Private Other Owner"],"access":{"pal":"Private Other PAL"}}')])
        self.c.executemany('INSERT INTO email_memberships VALUES(?,?,?,1)',[('owner@example.com',1,'owner'),('tenant@example.com',1,'tenant'),('other@example.com',2,'owner')]);self.c.commit()
    def tearDown(self):self.c.close();server.DB=self.old;self.temp.cleanup();self.env_patch.stop()
    def request(self,path,body=None,cookie='',origin='https://portal.test'):
        raw=json.dumps(body).encode() if body is not None else b'';out={}
        env={'PATH_INFO':path,'REQUEST_METHOD':'POST' if body is not None else 'GET','HTTP_ORIGIN':origin,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_COOKIE':cookie}
        def start(status,headers):out.update(status=status,headers=dict(headers))
        out['body']=b''.join(server.app(env,start));return out
    def session(self,phone):
        token=secrets.token_urlsafe(24);self.c.execute('INSERT INTO email_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),phone,int(time.time())+100));self.c.commit();return '__Host-session='+token
    def challenge(self, expires=None, ready=1):
        self.c.execute('INSERT INTO email_challenges VALUES(?,?,?,?,?)',('owner@example.com',server.otp_digest('owner@example.com','nonce','123456'),'nonce',expires or int(time.time())+600,ready));self.c.commit()
    def test_expired_and_pending_challenges_fail(self):
        self.challenge(int(time.time())-1)
        self.assertTrue(self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})['status'].startswith('401'))
        self.c.execute('UPDATE email_challenges SET expires=?,ready=0',(int(time.time())+600,));self.c.commit()
        self.assertTrue(self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})['status'].startswith('401'))
    def test_single_use_and_email_normalization(self):
        self.challenge()
        body={'email':' OWNER@EXAMPLE.COM ','code':'123456'}
        self.assertTrue(self.request('/api/verify-code',body)['status'].startswith('200'))
        self.assertTrue(self.request('/api/verify-code',body)['status'].startswith('401'))
    def test_send_failure_invalidates_code(self):
        with patch('server.send_email',side_effect=RuntimeError('private provider error')):
            r=self.request('/api/send-code',{'email':'owner@example.com'})
        self.assertTrue(r['status'].startswith('200'))
        self.assertIsNone(self.c.execute('SELECT 1 FROM email_challenges').fetchone())
    def test_five_attempts_block_even_correct_code(self):
        self.challenge()
        for _ in range(5): self.request('/api/verify-code',{'email':'owner@example.com','code':'000000'})
        self.assertTrue(self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})['status'].startswith('429'))
    def test_provider_rejection_logs_safe_reason_only(self):
        from urllib.error import HTTPError
        raw=json.dumps({'code':'unauthorized','message':'private-api-key owner@example.com 123456'}).encode()
        error=HTTPError('https://api.brevo.com/v3/smtp/email',401,'Unauthorized',{},io.BytesIO(raw))
        with patch('server.urlopen',side_effect=error), self.assertLogs('portal.delivery',level='WARNING') as logs:
            r=self.request('/api/send-code',{'email':'owner@example.com'})
        output=' '.join(logs.output)
        self.assertIn('unauthorized',output);self.assertIn('401',output)
        for secret in ['private-api-key','owner@example.com','123456']: self.assertNotIn(secret,output)
        self.assertTrue(r['status'].startswith('200'))
        self.assertIsNone(self.c.execute('SELECT 1 FROM email_challenges').fetchone())
    def test_public_photo_excludes_private_apartment_data(self):
        self.c.execute('INSERT INTO presentation VALUES(1,?)',('data:image/jpeg;base64,/9j/2Q==',));self.c.commit()
        r=self.request('/building-photo');self.assertTrue(r['status'].startswith('200'))
        self.assertEqual(r['headers']['Content-Type'],'image/jpeg');self.assertEqual(r['body'],b'\xff\xd8\xff\xd9')
        self.assertNotIn(b'Owner One',self.request('/')['body'])
    def test_photo_rejects_html_svg(self):
        with self.assertRaises(ValueError): server.photo_bytes('data:image/svg+xml;base64,PHN2Zz4=')
    def test_no_auth_no_data(self):
        for path in ['/api/apartments','/api/summary']:
            r=self.request(path);self.assertTrue(r['status'].startswith('401'));self.assertNotIn(b'98765',r['body'])
    def test_owner_and_tenant_only_their_apartment(self):
        for p in ['owner@example.com','tenant@example.com']:
            r=self.request('/api/apartments',cookie=self.session(p));d=json.loads(r['body']);self.assertEqual([a['apt'] for a in d['apartments']],[1]);self.assertNotIn(b'98765',r['body']);self.assertIn(b'Owner One',r['body']);self.assertNotIn(b'Private Other Owner',r['body']);self.assertIn(b'PAL One',r['body']);self.assertNotIn(b'Private Other PAL',r['body'])
    def test_revocation_immediate_for_existing_session(self):
        cookie=self.session('tenant@example.com');self.c.execute("UPDATE email_memberships SET active=0 WHERE role='tenant'");self.c.commit()
        self.assertTrue(self.request('/api/apartments',cookie=cookie)['status'].startswith('401'))
    def test_cross_origin_rejected(self):
        self.assertTrue(self.request('/api/send-code',{'email':'owner@example.com'},origin='https://evil.test')['status'].startswith('403'))
    def test_unknown_phone_never_gets_sms(self):
        with patch('server.send_email') as sms:
            r=self.request('/api/send-code',{'email':'unknown@example.com'});self.assertTrue(r['status'].startswith('200'));sms.assert_not_called()
    def test_approved_code_creates_secure_session(self):
        self.challenge()
        r=self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})
        cookie=r['headers']['Set-Cookie'];self.assertIn('Secure; HttpOnly; SameSite=Strict',cookie)
        self.assertTrue(self.request('/api/apartments',cookie=cookie.split(';')[0])['status'].startswith('200'))
    def test_failed_otp_no_cookie(self):
        with patch('server.send_email'):r=self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})
        self.assertTrue(r['status'].startswith('401'));self.assertNotIn('Set-Cookie',r['headers'])
    def test_send_throttled(self):
        with patch('server.send_email') as sms:
            self.request('/api/send-code',{'email':'owner@example.com'});r=self.request('/api/send-code',{'email':'owner@example.com'})
        self.assertTrue(r['status'].startswith('429'));self.assertEqual(sms.call_count,1)
    def test_logout_revokes_session(self):
        cookie=self.session('owner@example.com');self.request('/api/logout',{},cookie);self.assertTrue(self.request('/api/apartments',cookie=cookie)['status'].startswith('401'))
    def test_resident_cannot_write(self):
        cookie=self.session('owner@example.com');r=self.request('/api/apartments',{'paid':999},cookie);self.assertTrue(r['status'].startswith('404'))
    def test_browser_assets_contain_no_private_data(self):
        r=self.request('/');self.assertNotIn(b'98765',r['body']);self.assertNotIn(b'embedded-data',r['body'])

if __name__=='__main__':unittest.main()
