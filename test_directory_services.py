import json,unittest
import test_security as security
import directory_update
class DirectoryServicesTests(unittest.TestCase):
    setUp=security.IsolationTests.setUp
    tearDown=security.IsolationTests.tearDown
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    def admin(self):
        self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',));self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit();return self.session('owner@example.com')
    def test_permission_expansion_retains_unmatched_and_ambiguous_names(self):
        names=['אורי כהן','אנסטסיה גילמן כהן','קרן שרעבי']
        self.assertEqual(directory_update.permission_names('אורי ואנסטסיה',names),'אורי כהן\nאנסטסיה גילמן כהן')
        self.assertEqual(directory_update.permission_names('שיר שרעבי',names),'שיר שרעבי')
        self.assertEqual(directory_update.permission_names('אורי',['אורי כהן','אורי לוי']),'אורי')
    def test_merge_preserves_email_for_same_person_and_all_financial_fields(self):
        old={'paid':7654,'electricVehicle':{'holder':'Example'},'ownerContacts':[{'name':'כהן אורי','phone':'0501234567','email':'owner@example.com'}]}
        result=directory_update.merge(old,{'owner1Name':'אורי כהן','gymAccess':'אורי','palAccess':'אדם אחר'})
        self.assertEqual(result['ownerContacts'][0]['email'],'owner@example.com');self.assertEqual(result['paid'],7654);self.assertEqual(result['electricVehicle'],old['electricVehicle']);self.assertEqual(result['access']['gym'],'אורי כהן');self.assertEqual(result['access']['pal'],'אדם אחר')
    def test_import_is_owner_only_preserves_access_and_finances(self):
        cookie=self.admin();body={'directory':[{'apt':1,'owner1Name':'Updated Owner','owner1Email':'owner@example.com','tenant1Name':'New Tenant','tenant1Email':'new@example.com','gymAccess':'New Tenant'}]}
        self.assertTrue(self.request('/api/admin/directory/import',body,cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/directory/import',body,cookie=cookie)['status'].startswith('200'))
        self.assertEqual(json.loads(self.c.execute('SELECT payload FROM apartments WHERE apt=1').fetchone()['payload'])['paid'],100)
        self.assertEqual(self.c.execute("SELECT active FROM email_memberships WHERE email='tenant@example.com'").fetchone()['active'],1)
        self.assertIsNone(self.c.execute("SELECT role FROM email_memberships WHERE email='new@example.com'").fetchone())
        self.assertTrue(self.request('/api/admin/directory/import',{'directory':[{'apt':1,'owner1Name':''}]},cookie=cookie)['status'].startswith('400'))
    def test_service_directory_crud_and_reversible_unpublishing(self):
        cookie=self.admin();body={'name':'Example plumber','category':'Plumbing','phone':'050-1234567','url':'https://example.com','notes':'Information only','active':1}
        self.assertTrue(self.request('/api/services')['status'].startswith('401'))
        self.assertTrue(self.request('/api/admin/services',body,cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        self.assertTrue(self.request('/api/admin/services',body,cookie=cookie)['status'].startswith('200'))
        visible=json.loads(self.request('/api/services',cookie=self.session('tenant@example.com'))['body']);self.assertEqual(visible['providers'][0]['name'],body['name']);self.assertIn('אינו מהווה המלצה',visible['disclaimer']);self.assertNotIn('version',visible['providers'][0])
        record=json.loads(self.request('/api/admin/services',cookie=cookie)['body'])['providers'][0]
        self.assertTrue(self.request('/api/admin/services',{**record,'active':0},cookie=cookie)['status'].startswith('200'))
        self.assertEqual(json.loads(self.request('/api/services',cookie=self.session('tenant@example.com'))['body'])['providers'],[])
        self.assertTrue(self.request('/api/admin/services',{**record,'url':'javascript:alert(1)'},cookie=cookie)['status'].startswith('400'))
        self.assertTrue(self.request('/api/admin/services',record,cookie=cookie)['status'].startswith('409'))
