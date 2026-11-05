import unittest,json,base64,hashlib
from unittest.mock import patch
import test_security as security
import receipts,portal_rules
class ReceiptTests(unittest.TestCase):
    request=security.IsolationTests.request
    session=security.IsolationTests.session
    tearDown=security.IsolationTests.tearDown
    def setUp(self):
        security.IsolationTests.setUp(self)
        self.c.execute('UPDATE apartments SET payload=? WHERE apt=1',(json.dumps({'year':2026,'floor':1,'owners':['Owner One'],'ownerContacts':[{'name':'Owner One','email':'','phone':''}],'tenants':[],'tenantContacts':[],'monthlyPayments':[100]*12,'paid':1200}),));self.c.execute('INSERT INTO committee_account VALUES(1,?)',('owner@example.com',));self.c.execute('INSERT INTO administrators VALUES(?,1)',('owner@example.com',));self.c.commit()
        self.body={'apt':1,'year':2026,'months':[11],'kind':'dues','amount':'100.00','payer':'Owner One','paymentDate':'2026-11-03','method':'העברה בנקאית','reference':'228029'}
    def test_issuance_is_idempotent_and_download_is_scoped(self):
        with patch('receipt_docs.render',return_value=b'%PDF-1.7 immutable'):
            first=self.request('/api/admin/receipts/issue',self.body,cookie=self.session('owner@example.com'))
            self.assertTrue(first['status'].startswith('200'),first['body']);result=json.loads(first['body'])
            again=json.loads(self.request('/api/admin/receipts/issue',self.body,cookie=self.session('owner@example.com'))['body'])
        self.assertEqual(result['number'],'H-2026-000001');self.assertEqual(result['id'],again['id']);self.assertFalse(again['created'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM receipts').fetchone()['n'],1)
        path='/api/receipts/'+result['id']
        self.assertTrue(self.request(path,cookie=self.session('tenant@example.com'))['status'].startswith('200'))
        self.assertTrue(self.request(path,cookie=self.session('other@example.com'))['status'].startswith('404'))
        self.assertTrue(self.request(path)['status'].startswith('401'))
        listed=json.loads(self.request('/api/apartments',cookie=self.session('tenant@example.com'))['body'])
        self.assertEqual(listed['apartments'][0]['data']['receiptFiles'][0]['number'],result['number'])
    def test_residents_cannot_issue_and_missing_fields_do_not_consume_numbers(self):
        self.assertTrue(self.request('/api/admin/receipts/issue',self.body,cookie=self.session('tenant@example.com'))['status'].startswith('403'))
        for fields in [{'paymentDate':''},{'method':''},{'reference':''},{'amount':'0'},{'amount':'1.001'},{'months':[]}]:
            response=self.request('/api/admin/receipts/issue',{**self.body,**fields},cookie=self.session('owner@example.com'));self.assertTrue(response['status'].startswith('400'))
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM receipts').fetchone()['n'],0)
    def test_ev_receipts_do_not_leak_to_wrong_role(self):
        self.assertFalse(receipts.permitted('ev',61,['owner']));self.assertTrue(receipts.permitted('ev',61,['tenant']))
        self.assertTrue(receipts.permitted('ev',45,['owner']));self.assertFalse(receipts.permitted('ev',45,['tenant']))
    def test_pdf_render_is_deterministic_and_freezes_the_snapshot(self):
        data=json.loads(self.c.execute('SELECT payload FROM apartments WHERE apt=1').fetchone()['payload'])
        entry={'snapshot':data,'apt':1,'year':2026,'months':[11],'kind':'dues','amount':100,'payer':'Owner One','date':'03.11.2026','method':'העברה בנקאית','reference':'228029','issueDate':'05.11.2026','description':'ועד בית - נובמבר 2026','note':'03.11.2026 · העברה בנקאית','number':'H-2026-000001'}
        first=receipts.receipt_docs.render(entry);second=receipts.receipt_docs.render(entry)
        self.assertTrue(first.startswith(b'%PDF'));self.assertEqual(first,second)
