import json,time,unittest
from unittest.mock import patch
from datetime import datetime,timezone
import test_security as security
import telemetry,server

class MonitoringTests(unittest.TestCase):
    setUp=security.IsolationTests.setUp
    tearDown=security.IsolationTests.tearDown
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    challenge=security.IsolationTests.challenge
    def make_admin(self):
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',));self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
    def report(self,**values):
        self.make_admin();return self.request('/api/admin/monitoring',values,cookie=self.session('owner@example.com'))
    def test_monitoring_requires_single_committee_identity(self):
        self.make_admin()
        self.assertTrue(self.request('/api/admin/monitoring',{})['status'].startswith('401'))
        self.assertTrue(self.request('/api/admin/monitoring',{},cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.c.execute('INSERT INTO administrators VALUES(?,1)',('other@example.com',));self.c.commit()
        self.assertTrue(self.request('/api/admin/monitoring',{},cookie=self.session('other@example.com'))['status'].startswith('403'))
        cookie=self.session('owner@example.com');token=json.loads(self.request('/api/admin/dashboard-session',{},cookie=cookie)['body'])['token']
        r=self.request('/api/admin/monitoring',{'days':7},origin=server.DASHBOARD_ORIGIN,authorization='Bearer '+token)
        self.assertTrue(r['status'].startswith('200'));self.assertEqual(json.loads(r['body'])['timezone'],'Asia/Jerusalem')
    def test_authenticated_events_do_not_allow_identity_spoofing_or_other_apartments(self):
        cookie=self.session('tenant@example.com')
        self.assertTrue(self.request('/api/usage',{'page':'payments','apt':1})['status'].startswith('401'))
        self.assertTrue(self.request('/api/usage',{'page':'payments','apt':2},cookie=cookie)['status'].startswith('403'))
        self.assertTrue(self.request('/api/usage',{'page':'secret-path','apt':1},cookie=cookie)['status'].startswith('400'))
        self.request('/api/usage',{'page':'payments','apt':1,'email':'other@example.com','event':'login'},cookie=cookie)
        row=self.c.execute('SELECT * FROM usage_events').fetchone();self.assertEqual(row['email'],'tenant@example.com');self.assertEqual(row['event'],'view')
        self.request('/api/usage',{'page':'payments','apt':1},cookie=cookie)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'],1)
        self.request('/api/usage',{'page':'active','apt':1},cookie=cookie);self.request('/api/usage',{'page':'active','apt':1},cookie=cookie)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM usage_events WHERE event='active'").fetchone()['n'],1)
    def test_report_excludes_committee_default_and_splits_email_types(self):
        self.make_admin()
        telemetry.record(self.c,'tenant@example.com','view','payments',1,'resident')
        telemetry.record(self.c,'tenant@example.com','login',digest='resident')
        telemetry.record(self.c,'owner@example.com','view','apartment',1,'committee')
        telemetry.record(self.c,'owner@example.com','otp_accepted')
        telemetry.record(self.c,'tenant@example.com','otp_failed')
        self.c.execute('INSERT INTO notice_notifications VALUES(?,?,?,?,?)',('example',1,'accepted',3,int(time.time())));self.c.commit()
        data=telemetry.report(self.c,30)
        self.assertEqual(data['summary']['views'],1);self.assertEqual(data['summary']['active_users'],1)
        self.assertEqual(data['mail']['accepted'],4);self.assertEqual(data['mail']['failed'],1)
        self.assertNotIn('session_key',json.dumps(data));self.assertNotIn('owner@example.com',[u['email'] for u in data['users']])
        self.assertEqual(telemetry.report(self.c,30,True)['summary']['views'],2)
        self.assertIn('other@example.com',[u['email'] for u in data['users']])
    def test_login_and_otp_delivery_metrics(self):
        with patch('server.send_email'):
            self.request('/api/send-code',{'email':'tenant@example.com'})
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM usage_events WHERE event='otp_accepted'").fetchone()['n'],1)
        self.challenge();r=self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})
        self.assertTrue(r['status'].startswith('200'));self.assertEqual(self.c.execute("SELECT count(*) AS n FROM usage_events WHERE event='login'").fetchone()['n'],1)
        with patch('server.send_email',side_effect=RuntimeError('secret-provider-response')):
            self.request('/api/send-code',{'email':'other@example.com'})
        row=self.c.execute("SELECT * FROM usage_events WHERE event='otp_failed'").fetchone();self.assertEqual(row['email'],'other@example.com');self.assertNotIn('secret',json.dumps(dict(row)))
    def test_local_timezone_day_buckets_and_retention(self):
        stamp=int(datetime(2026,10,22,22,15,tzinfo=timezone.utc).timestamp())
        with patch('telemetry.time.time',return_value=stamp):
            telemetry.record(self.c,'tenant@example.com','view','gym',1,'session')
            data=telemetry.report(self.c,1)
        self.assertEqual(data['daily'][0]['date'],'2026-10-23');self.assertEqual(data['daily'][0]['views'],1)
        self.c.execute('UPDATE usage_events SET at=?',(int(time.time())-91*86400,));self.c.commit()
        telemetry.record(self.c,'tenant@example.com','view','pal',1,'session')
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'],1)
    def test_invalid_report_arguments_and_metric_failure_dont_break_login(self):
        self.make_admin();cookie=self.session('owner@example.com')
        for values in ({'days':365},{'days':True},{'includeCommittee':'yes'}):
            self.assertTrue(self.request('/api/admin/monitoring',values,cookie=cookie)['status'].startswith('400'))
        self.challenge()
        with patch('telemetry.record',return_value=False):
            self.assertTrue(self.request('/api/verify-code',{'email':'owner@example.com','code':'123456'})['status'].startswith('200'))
