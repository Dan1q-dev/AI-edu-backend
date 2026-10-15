"""Lossless semantic mapping. Models classify source IDs, never regenerate text."""
import json


class ImportFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def paragraph(text='', inline=None):
    return {'type': 'paragraph', 'content': inline or ([{'type': 'text', 'text': text}] if text else [])}


def element_node(element):
    kind, text = element['kind'], element.get('text', '')
    body = paragraph(text, element.get('inline'))
    if kind == 'heading':
        return {**body, 'type': 'heading', 'attrs': {'level': min(3, max(2, element.get('level', 2)))}}
    if kind == 'quote':
        return {'type': 'blockquote', 'content': [body]}
    if kind == 'code':
        return {'type': 'codeBlock', 'content': [{'type': 'text', 'text': text}] if text else []}
    if kind in ('bullet', 'ordered'):
        node = {'type': 'orderedList' if kind == 'ordered' else 'bulletList', 'content': [{'type': 'listItem', 'content': [body]}]}
        if kind == 'ordered':
            node['attrs'] = {'start': max(1, min(1000000, int(element.get('list_start', 1))))}
        return node
    if kind == 'formula':
        # Only explicitly marked LaTeX is safe to interpret as mathematics.
        return {'type': 'blockMath', 'attrs': {'latex': text}} if element.get('latex') else body
    if kind == 'table':
        rows = element['rows']
        if len(rows) > 200 or any(len(row) > 50 for row in rows):
            raise ImportFailure('document_limit')
        return {'type': 'table', 'content': [
            {'type': 'tableRow', 'content': [
                {'type': 'tableHeader' if cell.get('header') else 'tableCell',
                 'attrs': {'colspan': cell.get('colspan', 1), 'rowspan': cell.get('rowspan', 1)},
                 'content': [paragraph(cell.get('text', ''), cell.get('inline'))]} for cell in row]} for row in rows]}
    return body


def to_blocks(elements, images):
    blocks, pending, lists = [], [], []

    def flush():
        if pending:
            blocks.append({'type': 'TEXT', 'position': len(blocks), 'content': json.dumps({'type': 'doc', 'content': pending}, ensure_ascii=False), 'media': None, 'config': {}})
            pending.clear()
        lists.clear()

    for element in elements:
        if element['kind'] == 'image':
            flush()
            media = images[element['image']]
            blocks.append({'type': 'IMAGE', 'position': len(blocks), 'content': element.get('text', ''),
                           'media': media, 'media_url': f'/api/v1/media/{media}/', 'config': {'alt': element.get('text', ''), 'width': 'wide'}})
        else:
            node = element_node(element)
            if len(json.dumps({'type': 'doc', 'content': [node]}, ensure_ascii=False)) > 45000:
                raise ImportFailure('document_limit')
            if pending and len(json.dumps({'type': 'doc', 'content': pending + [node]}, ensure_ascii=False)) > 44000:
                flush()
            if node['type'] in ('bulletList', 'orderedList'):
                depth = min(max(0, int(element.get('list_level', 0))), len(lists))
                del lists[depth + 1:]
                current = lists[depth] if depth < len(lists) else None
                same = current and current[1] == element.get('list_id') and current[0]['type'] == node['type']
                if same and node['type'] == 'orderedList' and 'list_start' in element:
                    same = element['list_start'] == current[0]['attrs']['start'] + len(current[0]['content'])
                if same:
                    current[0]['content'].extend(node['content'])
                else:
                    del lists[depth:]
                    target = lists[-1][0]['content'][-1]['content'] if lists else pending
                    target.append(node)
                    lists.append((node, element.get('list_id')))
            else:
                lists.clear()
                pending.append(node)
    flush()
    if len(blocks) > 100:
        raise ImportFailure('document_limit')
    if not blocks:
        raise ImportFailure('empty_document')
    return blocks
