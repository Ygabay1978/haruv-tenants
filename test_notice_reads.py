import json,time,unittest
import test_security as security
import notice_reads

class NoticeReadTests(unittest.TestCase):
    setUp=security.IsolationTests.setUp
    tearDown=security.IsolationTests.tearDown
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    def notice(self, audience='all',apt=1):
        ident='a'*32
        self.c.execute('INSERT INTO notices VALUES(?,?,?,?,?,?,1,?,1)',(ident,apt,audience,'message','Title','Body',int(time.time())));self.c.commit()
        return ident
    def test_view_scope_identity_version_and_disabled_notice(self):
        ident=self.notice('owner')
        b={'id':ident,'version':1,'apt':1}
        self.assertTrue(self.request('/api/notices/view',b)['status'].startswith('401'))
        self.assertTrue(self.request('/api/notices/view',b,cookie=self.session('tenant@example.com'))['status'].startswith('404'))
        b['apt']=2
        self.assertTrue(self.request('/api/notices/view',b,cookie=self.session('owner@example.com'))['status'].startswith('404'))
        b.update(apt=1,version=2)
        self.assertTrue(self.request('/api/notices/view',b,cookie=self.session('owner@example.com'))['status'].startswith('404'))
        b.update(version=1,email='other@example.com')
        cookie=self.session('owner@example.com')
        for _ in range(2):self.assertTrue(self.request('/api/notices/view',b,cookie=cookie)['status'].startswith('200'))
        rows=self.c.execute('SELECT * FROM notice_reads').fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['email'],'owner@example.com')
        self.c.execute('UPDATE notices SET active=0');self.c.commit()
        self.assertTrue(self.request('/api/notices/view',b,cookie=cookie)['status'].startswith('404'))
    def test_readership_is_admin_only_and_per_version(self):
        ident=self.notice()
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',))
        self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
        self.assertTrue(self.request('/api/admin/monitoring',{},cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.request('/api/notices/view',{'id':ident,'version':1,'apt':1},cookie=self.session('tenant@example.com'))
        report=notice_reads.report(self.c)
        self.assertEqual(report[0]['viewed'],1)
        self.assertEqual([r['email'] for r in report[0]['recipients']],['tenant@example.com'])
        self.c.execute('UPDATE notices SET version=2');self.c.commit()
        self.assertEqual(notice_reads.report(self.c)[0]['viewed'],0)
        self.c.execute("UPDATE email_memberships SET active=0 WHERE email='tenant@example.com'");self.c.commit()
        self.assertEqual(notice_reads.report(self.c)[0]['recipients'],[])
