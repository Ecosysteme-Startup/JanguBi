"""Génère les déclinaisons de couleur (clair + sombre) des maquettes Jàngu Bi.

Principe : les 52 écrans de référence (Lumière clair) n'utilisent que 33 couleurs-tokens.
- Clair : substitution rôle → hex de la version.
- Sombre : substitution selon la PROPRIÉTÉ CSS où apparaît la couleur
  (texte / fond / filet / graphique), car un même token change de rôle en sombre.
"""
import re, json, os, glob, sys

BASE = {  # rôle -> hex de référence (Lumière clair)
 'paper':'F6F1E7','surface':'FBF8F2','surface2':'EFE8DA','ink':'1D1B17','ink2':'4B463E','ink3':'645D51',
 'line':'D8CEBB','lineField':'8C8271',
 'b50':'EEF2F8','b100':'DCE5F2','b200':'B9C9E2','b300':'8FA8CF','b400':'5A7FB8','b500':'2F5FA3',
 'b600':'1B4B8F','b700':'163D75','b800':'11305D','b900':'0C2244',
 'okT':'1F6B5C','okBg':'E3EFEA','warnT':'8A5A0B','warnBg':'F6EAD3','warnDot':'B7801F','errT':'A12A22','errBg':'F7E3DF',
 'litGreen':'2E6B3F','litViolet':'5B3A7E','litGoldRing':'9A7A2C','litGoldText':'7A5E1C','litRed':'A3262A','litRoseDot':'C77A93','litRoseText':'8E3F58',
 'white':'FFFFFF',
}
ROLE_OF = {v:k for k,v in BASE.items()}

# ---------- Versions claires ----------
LIGHT = {
 'lumiere': {},  # référence
 'ciel': {
  'paper':'FFFFFF','surface':'F7FAFD','surface2':'EDF3F9','ink':'0E1A2B','ink2':'3A4859','ink3':'586677',
  'line':'DDE5EE','lineField':'8391A4',
  'b50':'EEF6FC','b100':'D9EBF7','b200':'B3D8F0','b300':'7FC0E8','b400':'3FA3DD','b500':'1A8FCC',
  'b600':'0A6BA3','b700':'085887','b800':'06466C','b900':'052F49',
  'warnBg':'FBF1DF','okBg':'E4F2EE','errBg':'FBE8E5',
 },
 'atlantique': {
  'paper':'F1F4F4','surface':'FAFCFC','surface2':'E4EBEC','ink':'12212A','ink2':'3A4952','ink3':'54636C',
  'line':'D1DADD','lineField':'7D8C94',
  'b50':'E7F1F3','b100':'CFE3E8','b200':'A5CAD4','b300':'73ACBC','b400':'3F8BA1','b500':'1F6F87',
  'b600':'0B5870','b700':'08495D','b800':'063A4A','b900':'042533',
 },
 'cathedrale': {
  'paper':'FBFAF6','surface':'FFFFFF','surface2':'F0EDE4','ink':'16161F','ink2':'42414E','ink3':'5C5A68',
  'line':'DDD8CC','lineField':'888373',
  'b50':'EEEFF8','b100':'DCDEF1','b200':'B9BCE2','b300':'8F93CC','b400':'B08D3E','b500':'8F7130',
  'b600':'2B2F80','b700':'22266A','b800':'1B1E55','b900':'11133A',
 },
}

# ---------- Versions sombres (par propriété) ----------
STATES_DARK = {
 'text': {'okT':'7CCBB6','warnT':'E6B865','errT':'F2958B','litGreen':'86C596','litViolet':'BCA0DC','litGoldText':'DCC079','litRed':'EE8A83','litRoseText':'E6A7BB'},
 'bg':   {'okT':'3E9E88','okBg':'13302A','warnBg':'342710','warnDot':'D49B36','errT':'B8392F','errBg':'3B1815','litGreen':'4F9B63','litViolet':'8B66B6','litRed':'C4463F','litRoseDot':'D99BB0','white':'FFFFFF'},
 'line': {'okT':'5FB8A2','warnDot':'D49B36','errT':'E0776C','litGreen':'5FAA74','litViolet':'9C7CC6','litGoldRing':'C9A55A','litRed':'D0625B','litRoseDot':'D99BB0'},
 'gfx':  {'okT':'7CCBB6','warnT':'E6B865','errT':'F2958B','white':'FFFFFF'},
}

def dark(n):
    """n = dict des neutres/bleus sombres d'une version -> maps par propriété."""
    text = {'ink':n['T1'],'ink2':n['T2'],'ink3':n['T3'],'paper':n['On'],'surface':n['On'],'surface2':n['On'],
            'b600':n['P'],'b700':n['P2'],'b800':n['P'],'b900':n['P2'],'b50':n['On'],'b100':n['t100'],'b200':n['t200'],'b300':n['t300'],
            'line':n['L2'],'lineField':n['T3'],'white':'FFFFFF'}
    bg = {'paper':n['BG'],'surface':n['S1'],'surface2':n['S2'],'ink':n['S3'],'ink2':n['L2'],'ink3':n['L2'],
          'line':n['L1'],'lineField':n['L2'],
          'b50':n['k50'],'b100':n['k100'],'b200':n['k200'],'b300':n['k300'],'b400':n['k400'],'b500':n['k500'],
          'b600':n['PF'],'b700':n['PFh'],'b800':n['D8'],'b900':n['D9']}
    line = {'paper':n['BG'],'surface':n['S1'],'surface2':n['S2'],'ink':n['LS'],'ink2':n['T3'],'ink3':n['L2'],'line':n['L1'],'lineField':n['L2'],
            'b600':n['P'],'b700':n['P'],'b800':n['k200'],'b200':n['k300'],'b300':n['k400'],'b400':n['k400']}
    gfx = {'paper':n['BG'],'surface':n['S1'],'surface2':n['S2'],'ink':n['T1'],'ink2':n['T2'],'ink3':n['T3'],'line':n['L1'],'lineField':n['L2'],
           'b50':n['k50'],'b100':n['k100'],'b200':n['k300'],'b300':n['k400'],'b400':n['k400'],'b500':n['k500'],
           'b600':n['P'],'b700':n['P2'],'b800':n['D8'],'b900':n['D9']}
    for cat,m in (('text',text),('bg',bg),('line',line),('gfx',gfx)):
        m.update(STATES_DARK[cat])
    return {'text':text,'bg':bg,'line':line,'gfx':gfx}

DARK_N = {
 'lumiere': dict(BG='13120F',S1='1B1916',S2='25221D',S3='4A443B',T1='EEE8DC',T2='C9C1B2',T3='A39A8C',On='F6F1E7',
                 L1='37332C',L2='6F675A',LS='CFC7B8',P='9CB8EA',P2='BCD0F2',PF='2F5FA3',PFh='285393',D8='0F1C33',D9='0A1322',
                 t100='DCE5F2',t200='B9C9E2',t300='8FA8CF',k50='182131',k100='1D2A41',k200='2A3D5E',k300='3E5A87',k400='5A7FB8',k500='6F92C6'),
 'ciel':    dict(BG='0B1118',S1='111A24',S2='18232F',S3='3A4757',T1='E8EEF5',T2='BAC6D3',T3='92A2B4',On='F5F9FC',
                 L1='243142',L2='5F7085',LS='C7D2DE',P='7CC3EE',P2='A8D8F5',PF='0A6BA3',PFh='085E90',D8='082438',D9='061826',
                 t100='D9EBF7',t200='B3D8F0',t300='7FC0E8',k50='0F2233',k100='13304A',k200='1B4466',k300='26618F',k400='3FA3DD',k500='5AB3E4'),
 'atlantique': dict(BG='0B1214',S1='111B1E',S2='182528',S3='3A4A4F',T1='E6EEEF',T2='B6C5C8',T3='8EA1A6',On='F2F7F7',
                 L1='243236',L2='5E7176',LS='C4D1D4',P='7EC4D6',P2='A9DAE6',PF='0B5870',PFh='116782',D8='06303F',D9='042029',
                 t100='CFE3E8',t200='A5CAD4',t300='73ACBC',k50='0F2429',k100='133139',k200='1B4550',k300='28667A',k400='3F8BA1',k500='5AA5B9'),
 'cathedrale': dict(BG='0F0F16',S1='16161F',S2='1F1F2B',S3='44434F',T1='ECEBF3',T2='C1C0CE',T3='9897A9',On='F7F6FB',
                 L1='2E2D3B',L2='6C6A7D',LS='CDCBDA',P='AAAEEC',P2='C7CAF4',PF='3B40A0',PFh='4A50B3',D8='171A4B',D9='0D0E2B',
                 t100='DCDEF1',t200='B9BCE2',t300='8F93CC',k50='181A33',k100='1F2244',k200='2E3263',k300='454A8C',k400='C9A55A',k500='B08D3E'),
}

HEX = re.compile(r'#([0-9A-Fa-f]{6})\b')
def category(prefix):
    a = re.search(r'([a-zA-Z-]+)\s*[:=]\s*"?[^;:"{]*$', prefix)
    p = a.group(1).lower() if a else 'color'
    if p in ('color',): return 'text'
    if p.startswith('background') or p=='box-shadow': return 'bg'
    if p.startswith('border') or p in ('outline','text-decoration-color','column-rule'): return 'line'
    if p=='accent-color': return 'line'
    if p in ('fill','stroke','stop-color'): return 'gfx'
    return 'text'

def apply_light(html, v):
    m = LIGHT[v]
    def rep(mo):
        role = ROLE_OF.get(mo.group(1).upper())
        return '#'+m[role] if role and role in m else mo.group(0)
    return HEX.sub(rep, html)

def apply_dark(html, v):
    maps = dark(DARK_N[v])
    out=[];last=0
    for mo in HEX.finditer(html):
        role = ROLE_OF.get(mo.group(1).upper())
        cat = category(html[max(0,mo.start()-120):mo.start()])
        new = mo.group(0)
        if role and role in maps[cat]: new = '#'+maps[cat][role]
        out.append(html[last:mo.start()]); out.append(new); last=mo.end()
    out.append(html[last:])
    h=''.join(out)
    h = re.sub(r'rgba\(12,34,68,0\.3[05]\)','rgba(0,0,0,0.62)',h)
    h = h.replace('rgba(29,27,23,0.48)','rgba(0,0,0,0.62)')
    return h

# ---------- contrastes ----------
def lum(hx):
    r,g,b=[int(hx[i:i+2],16)/255 for i in (0,2,4)]
    f=lambda c: c/12.92 if c<=0.03928 else ((c+0.055)/1.055)**2.4
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)
def cr(a,b):
    la,lb=sorted([lum(a),lum(b)],reverse=True); return (la+0.05)/(lb+0.05)

def light_pal(v):
    p=dict(BASE); p.update(LIGHT[v]); return p
