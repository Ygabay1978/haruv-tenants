import unittest,tempfile,io,json,time,hashlib,os
from pathlib import Path
from unittest.mock import patch
import server

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.env_patch=patch.dict(os.environ, {'DATABASE_URL':os.environ.get('TEST_DATABASE_URL',''),'PORTAL_TEST_DATABASE':'1'})
        self.env_patch.start()
        self.temp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=str(Path(self.temp.name)/'db');server.ORIGIN='https://portal.test'
        self.c=server.connect()
        with self.c:
            for table in ['sessions','attempts','memberships','apartments','summary']: self.c.execute('DELETE FROM '+table)
        self.c.executemany('INSERT INTO apartments VALUES(?,?)',[(1,'{"paid":100}'),(2,'{"paid":98765}')])
        self.c.executemany('INSERT INTO memberships VALUES(?,?,?,1)',[('+972501111111',1,'owner'),('+972502222222',1,'tenant'),('+972503333333',2,'owner')]);self.c.commit()
    def tearDown(self):self.c.close();server.DB=self.old;self.temp.cleanup();self.env_patch.stop()
    def request(self,path,body=None,cookie='',origin='https://portal.test'):
        raw=json.dumps(body).encode() if body is not None else b'';out={}
        env={'PATH_INFO':path,'REQUEST_METHOD':'POST' if body is not None else 'GET','HTTP_ORIGIN':origin,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_COOKIE':cookie}
        def start(status,headers):out.update(status=status,headers=dict(headers))
        out['body']=b''.join(server.app(env,start));return out
    def session(self,phone):
        token='token-'+phone;self.c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),phone,int(time.time())+100));self.c.commit();return '__Host-session='+token
    def test_no_auth_no_data(self):
        for path in ['/api/apartments','/api/summary']:
            r=self.request(path);self.assertTrue(r['status'].startswith('401'));self.assertNotIn(b'98765',r['body'])
    def test_owner_and_tenant_only_their_apartment(self):
        for p in ['+972501111111','+972502222222']:
            r=self.request('/api/apartments',cookie=self.session(p));d=json.loads(r['body']);self.assertEqual([a['apt'] for a in d['apartments']],[1]);self.assertNotIn(b'98765',r['body'])
    def test_revocation_immediate_for_existing_session(self):
        cookie=self.session('+972502222222');self.c.execute("UPDATE memberships SET active=0 WHERE role='tenant'");self.c.commit()
        self.assertTrue(self.request('/api/apartments',cookie=cookie)['status'].startswith('401'))
    def test_cross_origin_rejected(self):
        self.assertTrue(self.request('/api/send-code',{'phone':'0501111111'},origin='https://evil.test')['status'].startswith('403'))
    def test_unknown_phone_never_gets_sms(self):
        with patch('server.twilio') as sms:
            r=self.request('/api/send-code',{'phone':'0509999999'});self.assertTrue(r['status'].startswith('200'));sms.assert_not_called()
    def test_approved_code_creates_secure_session(self):
        with patch('server.twilio',return_value={'status':'approved'}):
            r=self.request('/api/verify-code',{'phone':'0501111111','code':'123456'})
        cookie=r['headers']['Set-Cookie'];self.assertIn('Secure; HttpOnly; SameSite=Strict',cookie)
        self.assertTrue(self.request('/api/apartments',cookie=cookie.split(';')[0])['status'].startswith('200'))
    def test_failed_otp_no_cookie(self):
        with patch('server.twilio',return_value={'status':'pending'}):r=self.request('/api/verify-code',{'phone':'0501111111','code':'123456'})
        self.assertTrue(r['status'].startswith('401'));self.assertNotIn('Set-Cookie',r['headers'])
    def test_send_throttled(self):
        with patch('server.twilio',return_value={'status':'pending'}) as sms:
            self.request('/api/send-code',{'phone':'0501111111'});r=self.request('/api/send-code',{'phone':'0501111111'})
        self.assertTrue(r['status'].startswith('429'));self.assertEqual(sms.call_count,1)
    def test_logout_revokes_session(self):
        cookie=self.session('+972501111111');self.request('/api/logout',{},cookie);self.assertTrue(self.request('/api/apartments',cookie=cookie)['status'].startswith('401'))
    def test_resident_cannot_write(self):
        cookie=self.session('+972501111111');r=self.request('/api/apartments',{'paid':999},cookie);self.assertTrue(r['status'].startswith('404'))
    def test_browser_assets_contain_no_private_data(self):
        r=self.request('/');self.assertNotIn(b'98765',r['body']);self.assertNotIn(b'embedded-data',r['body'])

if __name__=='__main__':unittest.main()
