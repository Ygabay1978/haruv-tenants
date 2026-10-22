"""Build the resident summary from an explicit public-to-residents field allowlist."""
import json,re
from pathlib import Path
KEYS=('fixedCosts','fixedCostsTotal','annualIncome','currentMonthlyIncome','totalPaid','totalDue','collectionPct','totalExpenses','variableExpensesTotal','months','monthlyIncome','monthlyExpenses')
def render(html):
    match=re.search(r'<script\b[^>]*\bid=[\"\']embedded-summary[\"\'][^>]*>(.*?)</script>',html,re.S)
    if not match: raise ValueError('Missing resident summary')
    source=json.loads(match[1]);data={k:source.get(k) for k in KEYS}
    data['fixedCosts']=[{'name':str(r.get('name','')),'amount':r.get('amount',0)} for r in (source.get('fixedCosts') or [])]
    text=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
    return (Path(__file__).parent/'static'/'tenant-summary.html').read_text().replace('__SUMMARY__',text)
