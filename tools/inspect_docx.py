import io, sys, zipfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from lxml import etree

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'

path = sys.argv[1]
with zipfile.ZipFile(path) as z:
    xml = z.read('word/document.xml')
root = etree.fromstring(xml)

def omml_text(el):
    """Readable sketch of an OMML tree: structure tags + literal text."""
    tag = etree.QName(el).localname
    if tag == 't':
        return el.text or ''
    parts = [omml_text(c) for c in el]
    inner = ''.join(p for p in parts if p)
    if tag in ('f',):
        return f'FRAC[{inner}]'
    if tag in ('nary',):
        pr = el.find(M+'naryPr')
        ch = pr.find(M+'chr') if pr is not None else None
        sh = pr.find(M+'subHide') if pr is not None else None
        sp = pr.find(M+'supHide') if pr is not None else None
        c = ch.get(M+'val') if ch is not None else '?'
        flags = f"{sh.get(M+'val') if sh is not None else '-'}/{sp.get(M+'val') if sp is not None else '-'}"
        return f'NARY<{c} hide={flags}>[{inner}]'
    if tag == 'd':
        pr = el.find(M+'dPr')
        b = pr.find(M+'begChr') if pr is not None else None
        e = pr.find(M+'endChr') if pr is not None else None
        bb = b.get(M+'val') if b is not None else '('
        ee = e.get(M+'val') if e is not None else ')'
        return f'DELIM{bb!r}{ee!r}[{inner}]'
    if tag == 'acc':
        pr = el.find(M+'accPr'); ch = pr.find(M+'chr') if pr is not None else None
        return f'ACC<{ch.get(M+"val") if ch is not None else "?"}>[{inner}]'
    if tag == 'bar':
        return f'BAR[{inner}]'
    if tag == 'func':
        return f'FUNC[{inner}]'
    if tag == 'fName':
        return f'name{{{inner}}}'
    if tag == 'm':
        return f'MATRIX[{inner}]'
    if tag == 'mr':
        return f'(row {inner})'
    if tag == 'limLow':
        return f'LIMLOW[{inner}]'
    if tag == 'limUpp':
        return f'LIMUPP[{inner}]'
    if tag == 'rad':
        return f'RAD[{inner}]'
    if tag in ('sSub',):
        return f'SUB[{inner}]'
    if tag in ('sSup',):
        return f'SUP[{inner}]'
    if tag in ('sSubSup',):
        return f'SUBSUP[{inner}]'
    if tag == 'e':
        return f'{{{inner}}}'
    if tag == 'sub':
        return f'_{{{inner}}}'
    if tag == 'sup':
        return f'^{{{inner}}}'
    if tag == 'num':
        return f'num{{{inner}}}'
    if tag == 'den':
        return f'den{{{inner}}}'
    return inner

for p in root.iter(W+'p'):
    pieces = []
    for child in p:
        lname = etree.QName(child).localname
        if lname == 'r':
            pieces.append(''.join(t.text or '' for t in child.iter(W+'t')))
        elif lname == 'oMath':
            pieces.append('  ⟨INLINE ' + omml_text(child) + '⟩  ')
        elif lname == 'oMathPara':
            for om in child.iter(M+'oMath'):
                pieces.append('⟪DISPLAY ' + omml_text(om) + '⟫')
    line = ''.join(pieces).strip()
    if line:
        style = p.find(W+'pPr/'+W+'pStyle')
        s = style.get(W+'val') if style is not None else ''
        print(f'[{s or "Body"}] {line}')
