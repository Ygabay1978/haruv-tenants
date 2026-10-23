"""Committee-maintained informational service directory."""
from urllib.parse import urlsplit
DISCLAIMER='פרטי בעלי המקצוע ונותני השירותים מוצגים כמידע לנוחות הדיירים בלבד. פרסומם אינו מהווה המלצה, אישור או התחייבות של ועד הבית. הוועד אינו בודק ואינו ערב לטיב השירות, למחירו, לזמינותו, לרישוי או לביטוח של נותן השירות. בחירת נותן השירות, בדיקת התאמתו וההתקשרות עמו נעשות ישירות ובאחריות הדייר. אין באמור כדי לגרוע מאחריות שאינה ניתנת להתניה על פי דין.'
def values(body):
    def field(key,maximum):
        value=body.get(key,'')
        if not isinstance(value,str) or len(value.strip())>maximum:raise ValueError('שדה לא תקין')
        return value.strip()
    name=field('name',120);category=field('category',60);phone=field('phone',50);url=field('url',500);notes=field('notes',1500);active=body.get('active',1)
    if not name or not category or type(active) is not int or active not in (0,1):raise ValueError('יש להשלים שם ותחום')
    if url:
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:raise ValueError('קישור לא תקין')
    return name,category,phone,url,notes,active
