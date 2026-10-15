"""Attach native PDF glyph colors to exactly matching extracted text, never to OCR guesses."""
import ctypes
from contextlib import closing


def enrich_pdf_colors(path, elements):
    import pypdfium2 as pdfium
    raw = pdfium.raw
    with pdfium.PdfDocument(path) as document:
        for page_no in sorted({element.get('page') for element in elements if element.get('page')}):
            candidates = [element for element in elements if element.get('page') == page_no and not element.get('ocr') and element.get('text') and element.get('bbox')]
            if not candidates:
                continue
            with closing(document[page_no - 1]) as page, closing(page.get_textpage()) as textpage:
                highlights = []
                for index in range(raw.FPDFPage_GetAnnotCount(page)):
                    annot = raw.FPDFPage_GetAnnot(page, index)
                    try:
                        if raw.FPDFAnnot_GetSubtype(annot) != raw.FPDF_ANNOT_HIGHLIGHT:
                            continue
                        rect = raw.FS_RECTF()
                        channels = [ctypes.c_uint() for _ in range(4)]
                        if raw.FPDFAnnot_GetRect(annot, ctypes.byref(rect)) and raw.FPDFAnnot_GetColor(annot, raw.FPDFANNOT_COLORTYPE_Color, *[ctypes.byref(value) for value in channels]):
                            highlights.append((rect.left, rect.bottom, rect.right, rect.top, '#' + ''.join(f'{value.value:02x}' for value in channels[:3])))
                    finally:
                        raw.FPDFPage_CloseAnnot(annot)
                glyphs = []
                for index in range(min(500000, textpage.count_chars())):
                    code = raw.FPDFText_GetUnicode(textpage, index)
                    if not code or chr(code).isspace():
                        continue
                    left, bottom, right, top = textpage.get_charbox(index)
                    x, y = (left + right) / 2, (bottom + top) / 2
                    channels = [ctypes.c_uint() for _ in range(4)]
                    color = None
                    if raw.FPDFText_GetFillColor(textpage, index, *[ctypes.byref(value) for value in channels]) and channels[3].value:
                        color = '#' + ''.join(f'{value.value:02x}' for value in channels[:3])
                    highlight = next((color for l, b, r, t, color in highlights if l <= x <= r and b <= y <= t), None)
                    glyphs.append((chr(code), x, y, color, highlight))
                for element in candidates:
                    bbox = element['bbox']
                    left, right = sorted((bbox['l'], bbox['r']))
                    bottom, top = sorted((bbox['b'], bbox['t']))
                    if bbox.get('coord_origin') == 'TOPLEFT':
                        bottom, top = page.get_height() - top, page.get_height() - bottom
                    local = [glyph for glyph in glyphs if left - 1 <= glyph[1] <= right + 1 and bottom - 1 <= glyph[2] <= top + 1]
                    source = ''.join(glyph[0] for glyph in local)
                    target = ''.join(element['text'].split())
                    start = source.find(target)
                    if start < 0 or not target or source.find(target, start + 1) >= 0:
                        continue
                    matched = iter(local[start:start + len(target)])
                    base_marks = element.get('inline', [{}])[0].get('marks', [])
                    inline, previous = [], None
                    for character in element['text']:
                        glyph = previous if character.isspace() else next(matched)
                        previous = glyph
                        marks = list(base_marks)
                        if glyph and glyph[3]:
                            marks.append({'type': 'textStyle', 'attrs': {'color': glyph[3]}})
                        if glyph and glyph[4]:
                            marks.append({'type': 'highlight', 'attrs': {'color': glyph[4]}})
                        if inline and inline[-1].get('marks', []) == marks:
                            inline[-1]['text'] += character
                        else:
                            inline.append({'type': 'text', 'text': character, **({'marks': marks} if marks else {})})
                    element['inline'] = inline
