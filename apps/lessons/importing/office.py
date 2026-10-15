"""Read Office run colors and numbering from OOXML, without rewriting source text."""
from lxml import etree
from functools import lru_cache
from colorsys import rgb_to_hls, hls_to_rgb

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
HIGHLIGHTS = dict(zip(
    ('black', 'blue', 'cyan', 'green', 'magenta', 'red', 'yellow', 'white',
     'darkBlue', 'darkCyan', 'darkGreen', 'darkMagenta', 'darkRed', 'darkYellow', 'darkGray', 'lightGray'),
    ('000000', '0000ff', '00ffff', '00ff00', 'ff00ff', 'ff0000', 'ffff00', 'ffffff',
     '000080', '008080', '008000', '800080', '800000', '808000', '808080', 'c0c0c0')))


def hex_color(value):
    return '#' + value.lower() if value and len(value) == 6 and all(c in '0123456789abcdefABCDEF' for c in value) else None


@lru_cache(maxsize=64)
def theme_colors(part):
    return _theme_colors(part)


def _theme_colors(part, seen=None):
    seen = set() if seen is None else seen
    if part in seen:
        return {}
    seen.add(part)
    for rel in part.rels.values():
        if not rel.is_external and rel.reltype.endswith('/theme'):
            root = etree.fromstring(rel.target_part.blob)
            return {etree.QName(node).localname: (node[0].get('val') if node[0].tag.endswith('srgbClr') else node[0].get('lastClr'))
                    for node in root.findall('.//{%s}clrScheme/*' % A) if len(node)}
    for rel in part.rels.values():
        if not rel.is_external and rel.reltype.endswith(('/slideMaster', '/slideLayout')):
            result = _theme_colors(rel.target_part, seen)
            if result:
                return result
    return {}


def drawing_color(container, palette):
    if container is None:
        return None
    value = None
    for node in container:
        name = etree.QName(node).localname
        if name == 'srgbClr':
            value = node.get('val')
        elif name == 'schemeClr':
            key = {'tx1': 'dk1', 'tx2': 'dk2', 'bg1': 'lt1', 'bg2': 'lt2'}.get(node.get('val'), node.get('val'))
            value = palette.get(key)
        elif name == 'sysClr':
            value = node.get('lastClr')
        color = hex_color(value)
        if color:
            channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
            for transform in node:
                kind, amount = etree.QName(transform).localname, int(transform.get('val', '100000')) / 100000
                if kind in ('tint', 'shade'):
                    channels = [round(c + (255 - c) * amount) if kind == 'tint' else round(c * amount) for c in channels]
                elif kind in ('lumMod', 'lumOff'):
                    hue, lightness, saturation = rgb_to_hls(*[c / 255 for c in channels])
                    lightness = lightness * amount if kind == 'lumMod' else lightness + amount
                    channels = [round(c * 255) for c in hls_to_rgb(hue, min(1, max(0, lightness)), saturation)]
            return '#' + ''.join(f'{min(255, max(0, c)):02x}' for c in channels)
    return None


def run_colors(run, defaults=()):
    word = run._r.tag.startswith('{' + W + '}')
    ns = W if word else A
    properties = [run._r.find('{%s}rPr' % ns)]
    if word:
        style = run.style
        while style is not None:
            properties.append(style.element.find('{%s}rPr' % W))
            style = style.base_style
    properties.extend(defaults)
    palette = theme_colors(run.part)
    color = highlight = None
    for props in properties:
        if props is None:
            continue
        if word:
            node = props.find('{%s}color' % W)
            if color is None and node is not None:
                key = node.get('{%s}themeColor' % W)
                key = {'dark1': 'dk1', 'light1': 'lt1', 'dark2': 'dk2', 'light2': 'lt2', 'hyperlink': 'hlink', 'followedHyperlink': 'folHlink'}.get(key, key)
                color = hex_color(palette.get(key) or node.get('{%s}val' % W))
                if color:
                    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
                    for attr in ('themeShade', 'themeTint'):
                        factor = node.get('{%s}%s' % (W, attr))
                        if factor:
                            ratio = int(factor, 16) / 255
                            channels = [round(c * ratio) if attr == 'themeShade' else round(c + (255 - c) * (1 - ratio)) for c in channels]
                    color = '#' + ''.join(f'{c:02x}' for c in channels)
            node = props.find('{%s}highlight' % W)
            if highlight is None and node is not None:
                highlight = hex_color(HIGHLIGHTS.get(node.get('{%s}val' % W)))
            node = props.find('{%s}shd' % W)
            if highlight is None and node is not None:
                highlight = hex_color(node.get('{%s}fill' % W))
        else:
            color = color or drawing_color(props.find('{%s}solidFill' % A), palette)
            highlight = highlight or drawing_color(props.find('{%s}highlight' % A), palette)
    return color, highlight


def presentation_properties(paragraph):
    """Resolve local, textbox, layout and master paragraph defaults in priority order."""
    properties = [paragraph._p.find('{%s}pPr' % A)]
    frame = paragraph._parent
    level = paragraph.level + 1
    properties.append(frame._txBody.find('{%s}lstStyle/{%s}lvl%spPr' % (A, A, level)))
    shape = frame._parent
    if getattr(shape, 'is_placeholder', False):
        layout = paragraph.part.slide_layout
        placeholder = next((item for item in layout.placeholders if item.placeholder_format.idx == shape.placeholder_format.idx), None)
        if placeholder is not None and placeholder.has_text_frame:
            body = placeholder.text_frame._txBody
            properties.extend([body.find('{%s}p/{%s}pPr' % (A, A)), body.find('{%s}lstStyle/{%s}lvl%spPr' % (A, A, level))])
        master = layout.slide_master
        name = str(shape.placeholder_format.type)
        style = 'titleStyle' if 'TITLE' in name and 'SUBTITLE' not in name else 'bodyStyle' if 'BODY' in name or 'OBJECT' in name else 'otherStyle'
        p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
        properties.append(master.element.find('{%s}txStyles/{%s}%s/{%s}lvl%spPr' % (p, p, style, A, level)))
    return [props for props in properties if props is not None]


class WordLists:
    def __init__(self, document):
        self.numbering = document.part.numbering_part.element
        self.counters = {}

    def resolve(self, paragraph):
        properties = [paragraph._p.find('{%s}pPr' % W)]
        style = paragraph.style
        while style is not None:
            properties.append(style.element.find('{%s}pPr' % W))
            style = style.base_style
        num_id = level = None
        for props in properties:
            num = props.find('{%s}numPr' % W) if props is not None else None
            if num is not None:
                value = num.find('{%s}numId' % W)
                depth = num.find('{%s}ilvl' % W)
                if num_id is None and value is not None:
                    num_id = value.get('{%s}val' % W)
                if level is None and depth is not None:
                    level = int(depth.get('{%s}val' % W))
        if num_id == '0':
            return {'kind': 'paragraph'}
        if num_id is None:
            return {}
        level = min(8, max(0, level or 0))
        num = self.numbering.find('{%s}num[@{%s}numId="%s"]' % (W, W, num_id))
        if num is None:
            return {}
        abstract_id = num.find('{%s}abstractNumId' % W).get('{%s}val' % W)
        definition = self.numbering.find('{%s}abstractNum[@{%s}abstractNumId="%s"]/{%s}lvl[@{%s}ilvl="%s"]' % (W, W, abstract_id, W, W, level))
        override = num.find('{%s}lvlOverride[@{%s}ilvl="%s"]' % (W, W, level))
        replacement = override.find('{%s}lvl' % W) if override is not None else None
        if replacement is not None:
            definition = replacement
        if definition is None:
            return {}
        fmt = definition.find('{%s}numFmt' % W)
        kind = 'bullet' if fmt is not None and fmt.get('{%s}val' % W) == 'bullet' else 'ordered'
        start_node = definition.find('{%s}start' % W)
        start_override = override.find('{%s}startOverride' % W) if override is not None else None
        start = int((start_override if start_override is not None else start_node).get('{%s}val' % W)) if start_override is not None or start_node is not None else 1
        key = (num_id, level)
        ordinal = self.counters.get(key, start - 1) + 1
        self.counters[key] = ordinal
        for counter in list(self.counters):
            if counter[0] == num_id and counter[1] > level:
                del self.counters[counter]
        return {'kind': kind, 'list_id': num_id, 'list_level': level, 'list_start': ordinal}
