"""Decide which fallback is needed without changing source content."""
import re
import unicodedata


def pdf_ocr_mode(text, has_images=False, has_objects=True):
    visible = ''.join(char for char in text if not char.isspace())
    if not visible:
        return 'full' if has_objects else None
    damaged = sum(char == '\ufffd' or unicodedata.category(char) in ('Co', 'Cc', 'Cn') for char in visible)
    if damaged / len(visible) > 0.02:
        return 'full'
    return 'regions' if has_images else None


def uncertain_elements(elements):
    paragraphs = [element for element in elements if element['kind'] == 'paragraph' and element.get('text', '').strip()]
    unstructured = len(paragraphs) >= 3 and not any(element['kind'] == 'heading' for element in elements)
    candidates = []
    for element in paragraphs:
        text = element['text'].strip()
        short = len(text) <= 180 and len(text.splitlines()) <= 2
        emphasized = any(mark.get('type') in ('bold', 'code') for node in element.get('inline', []) for mark in node.get('marks', []))
        title_like = short and (emphasized or text.isupper() and len(text.split()) >= 2 or text.endswith(':'))
        syntax_like = bool(re.search(r'^(?:\s*(?:[-•]\s+|\d+(?:\.\d+)*[.)]?\s+|```|def\s+\w+\(|class\s+\w+|SELECT\s+|[«“]))', text))
        if element.get('ocr') or element.get('needs_structure_review') or title_like or syntax_like or unstructured and short:
            candidates.append(element)
    return candidates


def page_ranges(pages):
    """Group adjacent pages without OCRing the digital pages between them."""
    ranges = []
    for page in sorted(set(pages)):
        if ranges and page == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], page)
        else:
            ranges.append((page, page))
    return ranges
