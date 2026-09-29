import re, glob, os, sys
sys.path.insert(0, '../jangubi-v1')
from themes import BASE, LIGHT, apply_dark
ciel = LIGHT['ciel']
inv = {}
for role, base in BASE.items():
    v = ciel.get(role, base)
    inv.setdefault(v.upper(), base)
inv['FFFFFF'] = BASE['paper']
HEX = re.compile(r'#([0-9A-Fa-f]{6})\b')
def nbsp(h):
    def fix(m):
        t = m.group(0)
        t = re.sub(r'(?<=[\wÀ-ÿ»\)]) ([?!:;»])', ' \\1', t)
        t = re.sub(r'« ', '« ', t)
        return t
    body = h.split('</helmet>', 1)
    body[1] = re.sub(r'>[^<]+<', fix, body[1])
    return '</helmet>'.join(body)
os.makedirs('project', exist_ok=True)
for f in sorted(glob.glob('project/*.dc.html')):
    b = os.path.basename(f)
    if b.startswith('Sombre-'): continue
    h = nbsp(open(f).read()); open(f, 'w').write(h)
    def protect(m):
        st = m.group(0)
        if re.search(r'background(?:-color)?:\s*#FEFEFE', st, re.I):
            st = re.sub(r'(?<![-\w])color:\s*#([0-9A-Fa-f]{6})', r'color: @@\1@@', st)
        return st
    h2 = re.sub(r'style="[^"]*"', protect, h)
    d = HEX.sub(lambda m: '#' + inv.get(m.group(1).upper(), m.group(1).upper()), h2)
    d = apply_dark(d, 'ciel')
    d = re.sub(r'rgba\(14,\s*26,\s*43,\s*0?\.4\d?\)', 'rgba(0,0,0,0.62)', d)
    d = re.sub(r'rgba\(14,\s*26,\s*43,\s*(0?\.\d+)\)', lambda m: f'rgba(0,0,0,{min(0.5, float(m.group(1))*3):.2f})', d)
    # indicateurs d'accueil / barre de gestes en clair
    d = re.sub(r'(width: 1(?:34|08)px; height: [45]px;[^"]*?background: )#[0-9A-F]{6}', r'\1#E8EEF5', d)
    d = re.sub(r'@@([0-9A-Fa-f]{6})@@', r'#\1', d)
    d = re.sub(r'href="((?:APP|AND|WEB)-[^"]+\.dc\.html)"', r'href="Sombre-\1"', d)
    d = d.replace('<title>', '<title>Sombre · ', 1)
    open('project/Sombre-' + b, 'w').write(d)
print('ok')
