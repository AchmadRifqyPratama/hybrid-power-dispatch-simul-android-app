"""Laporan Studi Kelayakan / Simulasi Dispatch — PDF (reportlab).

Me-render model blok dari `content.build_report()` (isi identik dengan versi
Word). Font standar PDF (tanpa berkas font eksternal → aman untuk build .exe),
grafik matplotlib di-embed sebagai PNG. Tata letak: sampul berpita warna brand,
kendali dokumen + daftar isi otomatis, header/footer bernomor halaman.

PENTING: modul ini TIDAK menjalankan/mengubah mesin dispatch — hanya MEMBACA
hasil simulasi melalui `content.py`.
"""
from __future__ import annotations
import io
import re
from functools import partial

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, Image, PageBreak,
                                KeepTogether, ListFlowable, ListItem, CondPageBreak)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen import canvas as _canvas

from . import common as K
from .common import L
from .content import build_report

PAGE_W, PAGE_H = A4
MARGIN_L = MARGIN_R = 2.0 * cm
USABLE_W = PAGE_W - MARGIN_L - MARGIN_R

HX = colors.HexColor
DARK, GREEN, INK, GREY = HX(K.DARK), HX(K.GREEN), HX(K.INK), HX(K.GREY)
RULE, LIGHT, WHITE = HX(K.RULE), HX(K.LIGHT), colors.white
TONE = {'good': (HX(K.OK), HX('#EAF6EE')), 'warn': (HX(K.WARN), HX('#FDF3E7')),
        'bad': (HX(K.BAD), HX('#FBEAEA')), 'info': (HX(K.INFO), HX('#EAF0FB'))}
GROUP_BG = HX('#E3ECE6')


# ------------------------------------------------------------------ teks -------
_SYM = None


def _sym_font():
    """Font Unicode utk glyph di luar Helvetica (✓ ✗ ₂ ≤ ≥ Δ → ★ …).
    DejaVu Sans dibundel bersama matplotlib → tersedia juga di build .exe."""
    global _SYM
    if _SYM is not None:
        return _SYM
    _SYM = ''
    try:
        import os
        import matplotlib
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.fonts import addMapping
        d = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf')
        pdfmetrics.registerFont(TTFont('HPPSym', os.path.join(d, 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('HPPSym-B', os.path.join(d, 'DejaVuSans-Bold.ttf')))
        addMapping('HPPSym', 0, 0, 'HPPSym')
        addMapping('HPPSym', 1, 0, 'HPPSym-B')
        addMapping('HPPSym', 0, 1, 'HPPSym')
        addMapping('HPPSym', 1, 1, 'HPPSym-B')
        _SYM = 'HPPSym'
    except Exception:
        _SYM = ''
    return _SYM


def _winansi(c):
    try:
        c.encode('cp1252')
        return True
    except UnicodeEncodeError:
        return False


def _md(s):
    """Teks isi → markup Paragraph: escape & < > lalu **tebal** → <b>;
    glyph di luar Helvetica dibungkus font Unicode."""
    s = str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    sym = _sym_font()
    if sym and any(not _winansi(c) for c in s):
        s = ''.join(c if _winansi(c) else f'<font name="{sym}">{c}</font>' for c in s)
    return s


def _styles():
    ss = getSampleStyleSheet()
    base = dict(fontName='Helvetica', textColor=INK)
    S = {
        'h1': ParagraphStyle('h1', parent=ss['Heading1'], fontName='Helvetica-Bold',
                             fontSize=16, leading=20, textColor=DARK,
                             spaceBefore=2, spaceAfter=10),
        'h2': ParagraphStyle('h2', parent=ss['Heading2'], fontName='Helvetica-Bold',
                             fontSize=11.5, leading=15, textColor=DARK,
                             spaceBefore=12, spaceAfter=5),
        'body': ParagraphStyle('body', parent=ss['BodyText'], fontSize=9.5,
                               leading=14, alignment=TA_JUSTIFY, spaceAfter=6, **base),
        'note': ParagraphStyle('note', parent=ss['Normal'], fontSize=8, leading=11,
                               textColor=GREY, spaceAfter=6, fontName='Helvetica-Oblique'),
        'cap': ParagraphStyle('cap', parent=ss['Normal'], fontSize=8, leading=11,
                              textColor=GREY, alignment=TA_LEFT, spaceBefore=3,
                              spaceAfter=10),
        'tcap': ParagraphStyle('tcap', parent=ss['Normal'], fontSize=8.5, leading=11,
                               textColor=DARK, fontName='Helvetica-Bold', spaceBefore=4,
                               spaceAfter=4),
        'bullet': ParagraphStyle('bullet', parent=ss['BodyText'], fontSize=9.5,
                                 leading=13.5, spaceAfter=3, **base),
        'kl': ParagraphStyle('kl', parent=ss['Normal'], fontSize=7.5, leading=9.5,
                             textColor=GREY),
        'kv': ParagraphStyle('kv', parent=ss['Normal'], fontSize=13.5, leading=16,
                             textColor=DARK, fontName='Helvetica-Bold'),
        'ks': ParagraphStyle('ks', parent=ss['Normal'], fontSize=7, leading=9,
                             textColor=GREY),
        'ct': ParagraphStyle('ct', parent=ss['Normal'], fontSize=10, leading=13,
                             fontName='Helvetica-Bold'),
        'cx': ParagraphStyle('cx', parent=ss['Normal'], fontSize=8.5, leading=11.5,
                             textColor=INK),
        'meta_k': ParagraphStyle('mk', parent=ss['Normal'], fontSize=8.5, leading=11,
                                 textColor=GREY),
        'meta_v': ParagraphStyle('mv', parent=ss['Normal'], fontSize=9, leading=11.5,
                                 textColor=INK, fontName='Helvetica-Bold'),
        'plain_h': ParagraphStyle('ph', parent=ss['Heading1'], fontName='Helvetica-Bold',
                                  fontSize=14, leading=18, textColor=DARK,
                                  spaceBefore=4, spaceAfter=8),
    }
    return S


def _cell_style(size, bold=False, color=INK, align=TA_LEFT):
    return ParagraphStyle('c', fontName='Helvetica-Bold' if bold else 'Helvetica',
                          fontSize=size, leading=size * 1.28, textColor=color,
                          alignment=align)


_AL = {'l': TA_LEFT, 'r': 2, 'c': TA_CENTER}      # 2 = TA_RIGHT


# ------------------------------------------------------------------ tabel ------
def _table(b, S):
    size = b.get('font') or 8.3
    widths = [w * USABLE_W for w in (b.get('widths') or
                                     [1.0 / len(b['header'])] * len(b['header']))]
    al = b['align']
    head = [Paragraph(_md(h), _cell_style(size - 0.3, True, WHITE, _AL[al[j]]))
            for j, h in enumerate(b['header'])]
    data = [head]
    tones = b.get('tones') or {}
    groups = b.get('group_rows') or set()
    n = len(b['rows'])
    for i, r in enumerate(b['rows']):
        is_total = b.get('total') and i == n - 1
        if i in groups:
            data.append([Paragraph(_md(r[0]), _cell_style(size, True, DARK))]
                        + [''] * (len(r) - 1))
            continue
        row = []
        for j, v in enumerate(r):
            tone = tones.get((i, j))
            col = TONE[tone][0] if tone else INK
            row.append(Paragraph(_md(v), _cell_style(size, bool(is_total or tone), col,
                                                     _AL[al[j]])))
        data.append(row)
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    st = [('BACKGROUND', (0, 0), (-1, 0), DARK),
          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('LINEBELOW', (0, 1), (-1, -1), 0.4, RULE),
          ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
          ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5)]
    zebra = 0
    for i in range(n):
        ri = i + 1
        if i in groups:
            st += [('SPAN', (0, ri), (-1, ri)), ('BACKGROUND', (0, ri), (-1, ri), GROUP_BG)]
            zebra = 0
            continue
        zebra += 1
        if zebra % 2 == 0:
            st.append(('BACKGROUND', (0, ri), (-1, ri), LIGHT))
    if b.get('total') and n:
        st += [('LINEABOVE', (0, n), (-1, n), 1.0, DARK),
               ('BACKGROUND', (0, n), (-1, n), GROUP_BG)]
    t.setStyle(TableStyle(st))
    out = []
    if b.get('caption'):
        out.append(Paragraph(_md(b['caption']), S['tcap']))
    out.append(t)
    out.append(Spacer(1, 0.25 * cm))
    return out


def _kpis(b, S):
    items = b['items']
    cols = max(1, min(int(b.get('cols') or 4), len(items)))
    gap = 0.18 * cm
    cw = (USABLE_W - gap * (cols - 1)) / cols
    cells, row = [], []
    for lab, val, sub in items:
        inner = Table([[Paragraph(_md(lab), S['kl'])], [Paragraph(_md(val), S['kv'])],
                       [Paragraph(_md(sub or ''), S['ks'])]], colWidths=[cw - 0.5 * cm])
        inner.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0),
                                   ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                   ('TOPPADDING', (0, 0), (-1, -1), 1),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
        row.append(inner)
        if len(row) == cols:
            cells.append(row); row = []
    if row:
        cells.append(row + [''] * (cols - len(row)))
    widths = []
    for j in range(cols):
        widths += [cw] + ([gap] if j < cols - 1 else [])
    grid = []
    for r in cells:
        g = []
        for j, c in enumerate(r):
            g += [c] + ([''] if j < cols - 1 else [])
        grid.append(g)
    t = Table(grid, colWidths=widths, hAlign='LEFT')
    st = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
          ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]
    for ri, r in enumerate(cells):
        for j, c in enumerate(r):
            ci = j * 2
            if c == '':
                continue
            st += [('BACKGROUND', (ci, ri), (ci, ri), LIGHT),
                   ('LINEBEFORE', (ci, ri), (ci, ri), 2.2, GREEN),
                   ('LEFTPADDING', (ci, ri), (ci, ri), 8)]
    for ri in range(len(cells) - 1):
        st.append(('BOTTOMPADDING', (0, ri), (-1, ri), 6))
    t.setStyle(TableStyle(st))
    return [Spacer(1, 0.1 * cm), t, Spacer(1, 0.3 * cm)]


def _callout(b, S):
    fg, bg = TONE.get(b.get('tone'), TONE['info'])
    icon = {'good': '✓', 'warn': '!', 'bad': '✗', 'info': 'i'}.get(b.get('tone'), 'i')
    hexs = {'good': K.OK, 'warn': K.WARN, 'bad': K.BAD}.get(b.get('tone'), K.INFO)
    rows = [[Paragraph(f'<font color="{hexs}">{_md(icon)}  {_md(b["title"])}</font>',
                       S['ct'])]]
    if b.get('text'):
        rows.append([Paragraph(_md(b['text']), S['cx'])])
    t = Table(rows, colWidths=[USABLE_W])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), bg),
                           ('LINEBEFORE', (0, 0), (0, -1), 3.5, fg),
                           ('LEFTPADDING', (0, 0), (-1, -1), 10),
                           ('TOPPADDING', (0, 0), (-1, -1), 4),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    return [Spacer(1, 0.1 * cm), KeepTogether([t]), Spacer(1, 0.3 * cm)]


def _figure(b):
    buf = io.BytesIO(b['png'])
    iw, ih = ImageReader(io.BytesIO(b['png'])).getSize()
    w = USABLE_W * float(b.get('width') or 1.0)
    h = w * ih / iw
    maxh = PAGE_H * 0.62
    if h > maxh:
        w, h = w * maxh / h, maxh
    img = Image(buf, width=w, height=h)
    img.hAlign = 'CENTER'
    return img


def _eq(latex):
    buf, w_pt, h_pt = K.eq_png(latex, 11)
    maxw = USABLE_W * 0.9
    if w_pt > maxw:
        h_pt *= maxw / w_pt
        w_pt = maxw
    img = Image(buf, width=w_pt, height=h_pt)
    img.hAlign = 'CENTER'
    return img


# ----------------------------------------------------------- doc template ------
class _Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(path, pagesize=A4, leftMargin=MARGIN_L, rightMargin=MARGIN_R,
                         topMargin=2.3 * cm, bottomMargin=2.0 * cm, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      id='f', leftPadding=0, rightPadding=0, topPadding=0,
                      bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='p', frames=[frame])])

    def afterFlowable(self, fl):
        lvl = getattr(fl, '_toc_level', None)
        if lvl is not None:
            key = f'h{id(fl)}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(fl.getPlainText(), key, level=lvl, closed=True)
            self.notify('TOCEntry', (lvl, fl.getPlainText(), self.page, key))


class _Canvas(_canvas.Canvas):
    """Kanvas bernomor 'Halaman X / Y' + sampul berpita brand."""

    def __init__(self, *a, meta=None, **k):
        self._meta = meta or {}
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self._decorate(total)
            super().showPage()
        super().save()

    def _cover(self):
        m = self._meta
        band_h = 11.2 * cm
        self.setFillColor(DARK)
        self.rect(0, PAGE_H - band_h, PAGE_W, band_h, stroke=0, fill=1)
        self.setFillColor(GREEN)
        self.rect(0, PAGE_H - band_h - 0.18 * cm, PAGE_W, 0.18 * cm, stroke=0, fill=1)
        logo = K.asset('logo_akartha_dark.png') or K.asset('logo_akartha.png')
        if logo:
            try:
                iw, ih = ImageReader(logo).getSize()
                lw = 4.2 * cm
                self.drawImage(logo, MARGIN_L, PAGE_H - 1.3 * cm - lw * ih / iw,
                               width=lw, height=lw * ih / iw, mask='auto')
            except Exception:
                pass
        y = PAGE_H - 5.6 * cm
        self.setFillColor(HX('#8FD3A8'))
        self.setFont('Helvetica-Bold', 9.5)
        self.drawString(MARGIN_L, y, '  ·  '.join(a.upper() for a in m.get('aspects', [])))
        self.setFillColor(WHITE)
        self.setFont('Helvetica-Bold', 24)
        words, line, lines = m.get('title', '').split(), '', []
        for w in words:
            test = (line + ' ' + w).strip()
            if self.stringWidth(test, 'Helvetica-Bold', 24) > USABLE_W:
                lines.append(line); line = w
            else:
                line = test
        lines.append(line)
        yy = y - 1.0 * cm
        for ln in lines:
            self.drawString(MARGIN_L, yy, ln)
            yy -= 0.95 * cm
        self.setFont('Helvetica', 11)
        self.setFillColor(HX('#C9DDD1'))
        self.drawString(MARGIN_L, yy - 0.1 * cm, m.get('subtitle', ''))
        self.setFont('Helvetica-Bold', 14)
        self.setFillColor(WHITE)
        self.drawString(MARGIN_L, yy - 1.0 * cm, m.get('project', '')[:80])
        # kaki sampul
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN_L, 2.3 * cm, PAGE_W - MARGIN_R, 2.3 * cm)
        self.setFont('Helvetica', 7.5)
        self.setFillColor(GREY)
        self.drawString(MARGIN_L, 1.85 * cm, m.get('prepared', ''))
        self.drawRightString(PAGE_W - MARGIN_R, 1.85 * cm, m.get('footer', ''))
        self.drawString(MARGIN_L, 1.45 * cm, f"{m.get('doc_no', '')}  ·  Rev. "
                        f"{m.get('revision', '')}  ·  {m.get('status', '')}")

    def _decorate(self, total):
        page = self._pageNumber
        if page == 1:
            self._cover()
            return
        m = self._meta
        self.setStrokeColor(GREEN)
        self.setLineWidth(1.2)
        self.line(MARGIN_L, PAGE_H - 1.55 * cm, PAGE_W - MARGIN_R, PAGE_H - 1.55 * cm)
        self.setFont('Helvetica-Bold', 8)
        self.setFillColor(DARK)
        self.drawString(MARGIN_L, PAGE_H - 1.35 * cm, m.get('project', '')[:70])
        self.setFont('Helvetica', 8)
        self.setFillColor(GREY)
        self.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.35 * cm, m.get('header_right', ''))
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(MARGIN_L, 1.45 * cm, PAGE_W - MARGIN_R, 1.45 * cm)
        self.setFont('Helvetica', 7.5)
        self.drawString(MARGIN_L, 1.05 * cm, f"{m.get('doc_no', '')}  ·  Rev. "
                        f"{m.get('revision', '')}  ·  {m.get('footer', '')}")
        self.drawRightString(PAGE_W - MARGIN_R, 1.05 * cm,
                             L('Halaman', 'Page') + f' {page} / {total}')


# ================================================================ builder ======
def _cover_story(meta, S):
    story = [Spacer(1, 12.2 * cm)]
    rows = [(L('Klien', 'Client'), meta['client']), (L('Site', 'Site'), meta['site']),
            (L('Lokasi', 'Location'), meta['location'])]
    if meta.get('coords') and meta['coords'] != '-':
        rows.append((L('Koordinat', 'Coordinates'), meta['coords']))
    rows += [(L('Nomor dokumen', 'Document no.'), meta['doc_no']),
             (L('Revisi', 'Revision'), f"{meta['revision']} — {meta['status']}"),
             (L('Tanggal', 'Date'), meta['date'])]
    t = Table([[Paragraph(_md(k), S['meta_k']), Paragraph(_md(v), S['meta_v'])]
               for k, v in rows], colWidths=[4.2 * cm, USABLE_W - 4.2 * cm], hAlign='LEFT')
    t.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.4, RULE),
                           ('TOPPADDING', (0, 0), (-1, -1), 4),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                           ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story.append(t)
    if meta.get('verdict') is not None:
        story.append(Spacer(1, 0.6 * cm))
        tone = 'good' if meta['verdict'] else 'warn'
        story += _callout({'tone': tone, 'title': (
            L('Kesimpulan: layak secara finansial', 'Verdict: financially feasible')
            if meta['verdict'] else
            L('Kesimpulan: marginal — tinjau asumsi', 'Verdict: marginal — review assumptions'))},
            S)
    story.append(PageBreak())
    return story


def build_feasibility_pdf(path, cfg, result, datetimes=None, multi_result=None,
                          include_technical=True, include_financial=True):
    """Bangun laporan PDF di `path` (aspek teknis / finansial sesuai pilihan)."""
    meta, blocks = build_report(cfg, result, datetimes=datetimes,
                                multi_result=multi_result,
                                include_technical=include_technical,
                                include_financial=include_financial)
    S = _styles()
    story = _cover_story(meta, S)
    pending_head = []

    def flush_with(fl):
        """Judul menempel pada elemen berikutnya (hindari judul yatim)."""
        if pending_head:
            story.append(KeepTogether(pending_head + list(fl)))
            pending_head.clear()
        else:
            story.extend(fl)

    for b in blocks:
        t = b['t']
        if t == 'pagebreak':
            if pending_head:
                story.extend(pending_head); pending_head.clear()
            story.append(PageBreak())
        elif t == 'doc_control':
            story.append(Paragraph(L('Kendali Dokumen', 'Document Control'), S['plain_h']))
            flush_with(_table({'header': [L('Item', 'Item'), L('Keterangan', 'Details')],
                               'rows': [list(r) for r in b['rows']], 'align': ['l', 'l'],
                               'widths': [0.3, 0.7]}, S))
        elif t == 'toc':
            story.append(PageBreak())
            story.append(Paragraph(L('Daftar Isi', 'Contents'), S['plain_h']))
            toc = TableOfContents()
            toc.levelStyles = [
                ParagraphStyle('t0', fontName='Helvetica-Bold', fontSize=9.2, leading=12.8,
                               textColor=DARK, leftIndent=0, firstLineIndent=0),
                ParagraphStyle('t1', fontName='Helvetica', fontSize=8.5, leading=11.0,
                               textColor=INK, leftIndent=14, firstLineIndent=0)]
            toc.dotsMinLevel = 0
            story.append(toc)
        elif t in ('h1', 'h2'):
            txt = f"{b['num']}  {b['text']}" if t == 'h2' else f"{b['num']}.  {b['text']}"
            if t == 'h1' and not b['num'][0].isdigit():
                txt = f"{b['num']} — {b['text']}"
            para = Paragraph(_md(txt), S[t])
            if t == 'h1' or b['num'][0].isdigit():     # sub-bab lampiran tak masuk TOC
                para._toc_level = 0 if t == 'h1' else 1
            if t == 'h1':
                pending_head.append(para)
                rule = Table([['']], colWidths=[USABLE_W], rowHeights=[0.06 * cm])
                rule.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, -1), 1.3, GREEN)]))
                pending_head.append(rule)
                pending_head.append(Spacer(1, 0.2 * cm))
            else:
                pending_head.append(para)
        elif t == 'p':
            para = Paragraph(_md(b['text']), S['body'])
            if b.get('keep') or str(b['text']).rstrip().endswith(':'):
                pending_head.append(para)     # pengantar menempel ke isi berikut
            else:
                flush_with([para])
        elif t == 'note':
            para = Paragraph(_md(b['text']), S['note'])
            if b.get('keep'):
                pending_head.append(para)
            else:
                flush_with([para])
        elif t in ('bullets', 'numbered'):
            items = [ListItem(Paragraph(_md(x), S['bullet']), leftIndent=14)
                     for x in b['items']]
            lf = ListFlowable(items, bulletType='bullet' if t == 'bullets' else '1',
                              start='•' if t == 'bullets' else None,
                              bulletColor=GREEN if t == 'bullets' else DARK,
                              bulletFontSize=9 if t == 'bullets' else 9,
                              leftIndent=14, bulletFontName='Helvetica-Bold')
            flush_with([lf, Spacer(1, 0.15 * cm)])
        elif t == 'table':
            fl = _table(b, S)
            if len(b['rows']) <= 16 and not pending_head:
                fl = [KeepTogether(fl)]
            elif len(b['rows']) > 16:
                # tabel panjang: mulai di halaman baru bila sisa ruang tak cukup
                # (hindari ekor 2–5 baris di halaman berikutnya)
                est = (len(b['rows']) + 2) * (b.get('font') or 8.3) * 1.28 + \
                    (len(b['rows']) + 2) * 6.4
                story.append(CondPageBreak(min(est, PAGE_H - 5.5 * cm)))
                if pending_head:
                    story.extend(pending_head); pending_head.clear()
            flush_with(fl)
        elif t == 'kpis':
            flush_with(_kpis(b, S))
        elif t == 'callout':
            flush_with(_callout(b, S))
        elif t == 'figure':
            img = _figure(b)
            cap = Paragraph(_md(b['caption']), S['cap'])
            flush_with([KeepTogether([img, cap])])
        elif t == 'eq':
            flush_with([_eq(b['latex']), Spacer(1, 0.1 * cm)])
    if pending_head:
        story.extend(pending_head)

    doc = _Doc(path, title=f"{meta['title']} — {meta['project']}",
               author='Akartha Energy', subject=meta['title'])
    doc.multiBuild(story, canvasmaker=partial(_Canvas, meta=meta))
    return path
