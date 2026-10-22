import os,re,json,subprocess,tempfile,datetime,unicodedata,io
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from flask import Flask,request,jsonify,render_template
from werkzeug.utils import secure_filename

app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=5*1024*1024
BASE=Path(__file__).parent
LOCAL=BASE/'state.json'
SUPA_URL=os.getenv('SUPABASE_URL','').rstrip('/')
SUPA_KEY=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
AB='https://abslusovice.cz/'
SUD='https://www.sudslusovice.cz/obedove-menu.html'
DAYS=['pondělí','úterý','středa','čtvrtek','pátek']
DEFAULT={'favorites':['řízek','svíčková','guláš'],'prerovska':{},'updated':None}

def load_state():
    if SUPA_URL and SUPA_KEY:
        try:
            r=requests.get(f'{SUPA_URL}/rest/v1/app_state',params={'id':'eq.main','select':'data'},headers={'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY},timeout=12)
            r.raise_for_status();rows=r.json()
            if rows:return {**DEFAULT,**rows[0]['data']}
        except Exception as e:app.logger.warning('DB read failed: %s',e)
    if LOCAL.exists():
        try:return {**DEFAULT,**json.loads(LOCAL.read_text(encoding='utf-8'))}
        except Exception:pass
    demo=BASE/'demo-data.json'
    if demo.exists():return {**DEFAULT,**json.loads(demo.read_text(encoding='utf-8'))}
    return DEFAULT.copy()

def save_state(data):
    if SUPA_URL and SUPA_KEY:
        r=requests.post(f'{SUPA_URL}/rest/v1/app_state',json={'id':'main','data':data},headers={'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates'},timeout=15)
        r.raise_for_status();return
    LOCAL.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def today():return datetime.datetime.now(ZoneInfo('Europe/Prague')).date()
def clean(s):return re.sub(r'\s+',' ',s).strip()
def norm(s):return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if unicodedata.category(c)!='Mn')
def dish(name,restaurant,price=None,day=None,kind='main',note=''):
    return {'name':clean(name),'restaurant':restaurant,'price':price,'day':day,'kind':kind,'note':note}

def fetch_ab():
    html=requests.get(AB,timeout=15,headers={'User-Agent':'Mozilla/5.0'});html.raise_for_status()
    soup=BeautifulSoup(html.text,'html.parser')
    h=next((x for x in soup.find_all(['h2','h3','h4']) if 'denni menu' in norm(x.get_text(' ',strip=True))),None)
    if not h:raise ValueError('Nadpis denního menu nebyl nalezen')
    date_el=h.find_next(['h2','h3','h4'])
    m=re.search(r'(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})',date_el.get_text(' ',strip=True)) if date_el else None
    if not m:raise ValueError('Nelze zjistit datum menu AB')
    date=datetime.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
    chunks=[]
    for e in date_el.next_elements:
        if getattr(e,'name',None)=='h2' and e is not date_el:break
        if getattr(e,'name',None) in ('li','p') and e.find_parent(['li','p']) is None:
            chunks.append(e.get_text(' ',strip=True))
    if not chunks:
        chunks=[]
        for e in date_el.next_elements:
            if getattr(e,'name',None)=='h2' and e is not date_el:break
            if isinstance(e,str):chunks.append(str(e))
    raw=' '.join(chunks)
    raw=re.sub(r'(?i)\b(hlavní jídlo|polévka)\s*:',r' | \1: ',raw)
    raw=re.sub(r'(?<!\w)(?=[1-9]\s*[.)]\s*[A-Za-zÁ-ž])',' | ',raw)
    out=[];kind='main'
    for part in raw.split('|'):
        part=clean(part)
        if not part:continue
        if re.search(r'(?i)^pol[eé]vka\s*:',part):
            kind='soup';part=re.sub(r'(?i)^pol[eé]vka\s*:\s*','',part)
        if re.search(r'(?i)^hlavn[ií] j[ií]dlo\s*:',part):
            kind='main';part=re.sub(r'(?i)^hlavn[ií] j[ií]dlo\s*:\s*','',part)
        numbered=bool(re.match(r'^\d+[.)]\s*',part))
        part=re.sub(r'^\d+[.)]\s*','',part)
        part=re.sub(r'\s*\*?\s*\([\d, ]+\)\s*$','',part).strip(' *')
        if len(part)>3 and (numbered or re.search(r'\([\d, ]+\)',part) or kind=='soup'):
            if not any(x['name']==part for x in out):out.append(dish(part,'AB Slušovice',day=date,kind=kind))
            if kind=='soup':kind='main'
    if not out:raise ValueError('Z webu AB se nepodařilo získat položky')
    return out,date

def parse_pdf(data):
    import fitz
    doc=fitz.open(stream=data,filetype='pdf')
    pages=[]
    for page in doc:
        text=page.get_text(sort=True)
        if not re.search(r"(?i)(pondělí|úterý|středa|čtvrtek|pátek)\s*\d{1,2}",text):
            import pytesseract
            from PIL import Image
            pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False)
            text=pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes('png'))),lang='ces+eng')
        pages.append(text)
    return '\n'.join(pages)

def parse_sud_menu(text):
    out=[];current=None;expect_soup=False
    for raw in text.splitlines():
        line=clean(raw)
        if not line:continue
        w=re.search(r'(?i)\b(pondělí|úterý|středa|čtvrtek|pátek)\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})',line)
        if w:
            try:current=datetime.date(int(w[4]),int(w[3]),int(w[2])).isoformat()
            except ValueError:current=None
            expect_soup=True;continue
        if not current:continue
        if re.search(r'(?i)(seznam alergen|zákaz prodeje)',line):break
        if re.fullmatch(r'\d{2,3}\s*(?:Kč|Kc|KE)?',line,re.I):continue
        numbered=re.match(r'^(?:[1-4]\s*[.)]?\s+)(.+)$',line)
        if numbered:
            name=clean(numbered[1]);expect_soup=False
            if len(name)>8:out.append(dish(name,'SUD Slušovice',day=current))
        elif expect_soup and len(line)>8 and not re.search(r'(?i)restaurace|jídelníček',line):
            out.append(dish(line,'SUD Slušovice',day=current,kind='soup'));expect_soup=False
    return out

def fetch_sud():
    # SUD publishes the current weekly PDF in a public Supabase Storage object.
    # The ?v=... cache-buster changes, but the object path remains constant.
    primary='https://xlurxdjzjftukwicctqr.supabase.co/storage/v1/object/public/menu/menu.pdf'
    candidates=[primary]
    try:
        r=requests.get(SUD,timeout=15,headers={'User-Agent':'Mozilla/5.0'})
        r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        for a in soup.find_all('a',href=True):
            if '.pdf' in a['href'].lower():
                u=urljoin(SUD,a['href'])
                if u not in candidates:candidates.append(u)
    except requests.RequestException as e:
        app.logger.warning('SUD website lookup failed: %s',e)
    errors=[]
    for pdfurl in candidates:
        try:
            pr=requests.get(pdfurl,timeout=30,headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'},params={'v':str(int(datetime.datetime.now().timestamp()))} if '?' not in pdfurl else None)
            pr.raise_for_status()
            if not pr.content.startswith(b'%PDF'):
                raise ValueError('Odkaz nevrátil PDF')
            raw=parse_pdf(pr.content)
            items=parse_sud_menu(raw)
            if not items:items=parse_generic_menu(raw,'SUD Slušovice')
            if not items:raise ValueError('Z PDF se nepodařilo rozpoznat jednotlivá jídla')
            # Do not display an old week just because OCR managed to parse it.
            dates=[datetime.date.fromisoformat(x['day']) for x in items if x.get('day')]
            if dates and not (min(dates) <= today() <= max(dates)):
                raise ValueError('PDF obsahuje jiný týden (%s až %s)'%(min(dates),max(dates)))
            return items,pdfurl
        except Exception as e:
            errors.append('%s: %s'%(pdfurl.split('?')[0],str(e)))
            app.logger.warning('SUD PDF failed: %s',errors[-1])
    raise ValueError('SUD: '+ ' | '.join(errors)[:600])

def parse_generic_menu(text,restaurant):
    lines=[clean(x) for x in text.splitlines() if clean(x)]
    out=[];current=None;week_start=None
    for line in lines:
        w=re.search(r'\b(pondělí|úterý|středa|čtvrtek|pátek)\b\s*(\d{1,2})\s*[.]\s*(\d{1,2})\s*[.]?\s*(\d{4})?',line,re.I)
        if w:
            y=int(w[4]) if w[4] else today().year
            try:current=datetime.date(y,int(w[3]),int(w[2])).isoformat()
            except ValueError:current=None
            line=clean(line[w.end():])
        if not current:continue
        if not line:continue
        if re.match(r'^(polévka|polevka)\s*:',line,re.I):
            name=clean(line.split(':',1)[1]);
            if name:out.append(dish(re.sub(r'\s*\([\d, ]+\)$','',name),restaurant,day=current,kind='soup'))
            continue
        # Lines with numbered menu entries, or explicit CZK prices.
        match=re.match(r'^(?:\d+[.)]\s*)?(?:(?:\d+\s*g|\d+\s*ks)\s+)?(.+?)\s+(\d{2,3})\s*(?:Kč|,-)\s*$',line,re.I)
        numbered=re.match(r'^\d+[.)]\s*(?:(?:\d+\s*g|\d+\s*ks)\s+)?(.+)$',line,re.I)
        if match:out.append(dish(re.sub(r'\s*\([\d, ]+\)$','',match[1]),restaurant,int(match[2]),current))
        elif numbered:out.append(dish(re.sub(r'\s*\([\d, ]+\)$','',numbered[1]),restaurant,day=current))
    return out

def parse_prerovska(text):
    # Word extraction keeps paragraphs but often splits day headings from menu entries.
    lines=[clean(x) for x in text.splitlines() if clean(x)]
    out=[];current=None;kind='main';year=today().year
    ym=re.search(r'(20\d\d)',text)
    if ym:year=int(ym[1])
    for line in lines:
        d=re.search(r'\b(pondělí|úterý|středa|čtvrtek|pátek)\b\s*(\d{1,2})\s*[.]\s*(\d{1,2})',line,re.I)
        if d:
            try:current=datetime.date(year,int(d[3]),int(d[2])).isoformat()
            except ValueError:current=None
            line=clean(line[d.end():]);kind='main'
        if not current:continue
        if re.search(r'\bpolévka\s*:',line,re.I):
            name=clean(re.split(r'polévka\s*:',line,flags=re.I)[-1]);name=re.sub(r'\s*\([\d, ]+\).*','',name)
            if name:out.append(dish(name,'Přerovská restaurace',day=current,kind='soup'))
            continue
        match=re.match(r'^([123])[.)]\s*(?:(?:\d+\s*g|\d+\s*ks)\s+)?(.+)$',line,re.I)
        if match:
            name=re.sub(r'\s*\([\d, ]+\).*','',match[2]);out.append(dish(name,'Přerovská restaurace',165,current))
        elif out and out[-1]['day']==current and out[-1]['kind']=='main' and line.startswith('('):
            pass
    return out

def word_text(data,filename):
    ext=Path(filename).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/('menu'+ext);path.write_bytes(data)
        if ext=='.doc':
            result=subprocess.run(['antiword','-m','UTF-8.txt','-w','0',str(path)],capture_output=True,text=True,timeout=20)
            if result.returncode:raise ValueError('Soubor DOC nelze přečíst: '+result.stderr[:100])
            return result.stdout
        if ext=='.docx':
            from docx import Document
            doc=Document(io.BytesIO(data));return '\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(' '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows)
        raise ValueError('Povolené soubory jsou .doc a .docx')

def authorized():
    supplied=request.headers.get('X-Admin-Password','')
    encoded=request.headers.get('X-Admin-Password-B64','')
    if encoded:
        import base64
        try:supplied=base64.b64decode(encoded,validate=True).decode('utf-8')
        except (ValueError,UnicodeError):return False
    import hmac
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(supplied,ADMIN_PASSWORD)

@app.get('/')
def home():return render_template('index.html')

@app.get('/api/menu')
def menu():
    date=request.args.get('date') or today().isoformat()
    try:datetime.date.fromisoformat(date)
    except ValueError:return jsonify(error='Neplatné datum'),400
    state=load_state();items=[x for x in state.get('prerovska',{}).get('items',[]) if x['day']==date]
    sources={'prerovska':{'status':'ok' if state.get('prerovska',{}).get('items') else 'missing','updated':state.get('updated')}}
    try:
        ab,abdate=fetch_ab()
        if abdate==date:items+=ab;sources['ab']={'status':'ok','date':abdate}
        else:sources['ab']={'status':'other_date','date':abdate}
    except Exception as e:sources['ab']={'status':'error','message':str(e)}
    try:
        sud,pdfurl=fetch_sud()
        items += [x for x in sud if x['day']==date]
        sources['sud']={'status':'ok' if sud else 'unreadable','url':pdfurl}
    except Exception as e:sources['sud']={'status':'error','message':str(e)}
    fav=state.get('favorites',[])
    for x in items:x['favorite']=any(norm(f) in norm(x['name']) for f in fav if f.strip())
    items.sort(key=lambda x:(not x['favorite'],x['kind']!='main',x['restaurant'],x['name']))
    return jsonify(date=date,items=items,favorites=fav,sources=sources)

@app.post('/api/admin/upload')
def upload():
    if not authorized():return jsonify(error='Nesprávné heslo správce'),403
    f=request.files.get('file')
    if not f or Path(f.filename).suffix.lower() not in ('.doc','.docx'):return jsonify(error='Nahraj DOC nebo DOCX'),400
    try:
        text=word_text(f.read(),f.filename);items=parse_prerovska(text)
        if len(items)<3:raise ValueError('Z dokumentu se nepodařilo rozpoznat dost jídel; zkontroluj jeho strukturu.')
        state=load_state();state['prerovska']={'items':items,'filename':secure_filename(f.filename)};state['updated']=datetime.datetime.now(ZoneInfo('Europe/Prague')).isoformat();save_state(state)
        return jsonify(ok=True,count=len(items),days=sorted(set(x['day'] for x in items)))
    except Exception as e:return jsonify(error=str(e)),400

@app.post('/api/admin/favorites')
def favorites():
    if not authorized():return jsonify(error='Nesprávné heslo správce'),403
    terms=request.json.get('favorites',[])
    if not isinstance(terms,list) or len(terms)>50 or any(not isinstance(t,str) or len(t)>60 for t in terms):return jsonify(error='Neplatné preference'),400
    state=load_state();state['favorites']=[t.strip() for t in terms if t.strip()];save_state(state)
    return jsonify(ok=True,favorites=state['favorites'])

if __name__=='__main__':app.run(debug=True,port=5000)
