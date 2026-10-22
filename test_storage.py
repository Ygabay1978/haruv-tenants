import os, tempfile, unittest, io, json, hashlib, time
from pathlib import Path
from unittest.mock import patch
import server, storage
from import_data import import_data

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=str(Path(self.t.name)/'db')
        self.env=patch.dict(os.environ,{'DATABASE_URL':os.environ.get('TEST_DATABASE_URL',''),'PORTAL_TEST_DATABASE':'1','BREVO_API_KEY':'test','EMAIL_FROM':'board@example.com','OTP_SECRET':'x'*40});self.env.start()
        c=server.connect()
        with c:
            for table in ['presentation','email_challenges','email_sessions','memberships','sessions','attempts','email_memberships','apartments','summary']:c.execute('DELETE FROM '+table)
        c.close()
    def tearDown(self):self.env.stop();server.DB=self.old;self.t.cleanup()
    def test_import_survives_reconnection_and_revokes_departed_contact(self):
        folder=Path(self.t.name)
        full=folder/'full.html';summary=folder/'tenants.html'
        data={'residents':[{'apt':1,'monthly':100,'annual':1200,'paid':200,'due':1000,'monthlyPayments':[100,100]}],
              'directory':[{'apt':1,'owner1Email':'owner@example.com','tenant1Email':'tenant@example.com','owner1Name':'Example Owner','owner2Name':'Second Owner','tenant1Name':'Example Tenant','owner1Phone':'0501111111','gymAccess':'Gym Person','palAccess':'PAL Person'}]}
        def save():full.write_text('<script id="embedded-data" type="application/json">'+json.dumps(data)+'</script>')
        summary.write_text('<script id="embedded-summary" type="application/json">{}</script>')
        save();self.assertEqual(import_data(full,summary)['email_apartment_roles'],2)
        c=server.connect();self.assertTrue(server.allowed(c,'tenant@example.com'))
        c.execute('UPDATE email_memberships SET active=0 WHERE email=?',('owner@example.com',));c.commit();c.close()
        data['directory'][0]['tenant1Email']=None;data['residents'][0]['paid']=300;save();import_data(full,summary)
        c=server.connect();self.assertFalse(server.allowed(c,'tenant@example.com'));self.assertFalse(server.allowed(c,'owner@example.com'))
        self.assertEqual(json.loads(c.execute('SELECT payload FROM apartments WHERE apt=1').fetchone()['payload'])['paid'],300)
        payload=json.loads(c.execute('SELECT payload FROM apartments WHERE apt=1').fetchone()['payload'])
        self.assertEqual(payload['owners'],['Example Owner','Second Owner']);self.assertEqual(payload['tenants'],['Example Tenant'])
        self.assertEqual(payload['access'],{'gym':'Gym Person','pal':'PAL Person'})
        self.assertNotIn('owner1Phone',payload);self.assertNotIn('owner1Email',payload);c.close()
    def test_rate_limit_persists_across_connections(self):
        c=server.connect();self.assertTrue(server.limit(c,'test',1,60));c.close()
        c=server.connect();self.assertFalse(server.limit(c,'test',1,60));c.close()
    def test_render_refuses_sqlite_fallback(self):
        with patch.dict(os.environ,{'DATABASE_URL':'','RENDER':'true'}):
            with self.assertRaises(RuntimeError):server.connect()
    def test_database_error_is_sanitized(self):
        env={'PATH_INFO':'/api/status','REQUEST_METHOD':'GET'};result={}
        def start(status,headers):result['status']=status
        with patch('server.connect',side_effect=RuntimeError('secret-database-password')):
            raw=b''.join(server.app(env,start))
        self.assertTrue(result['status'].startswith('503'));self.assertNotIn(b'secret-database-password',raw)

if __name__=='__main__':unittest.main()
