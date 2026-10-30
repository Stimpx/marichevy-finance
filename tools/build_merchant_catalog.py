#!/usr/bin/env python3
"""Embed the curated merchant names and checked local SVG marks in the single-file UI.

No network access, account data or remote image URLs are used by this builder.
The SVG source files and their provenance remain in tools/merchant_logos/;
the family release needs only its usual index.html and icons.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = 'http://www.w3.org/2000/svg'
TAGS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
        'polygon', 'defs', 'clipPath', 'mask', 'linearGradient', 'radialGradient', 'stop', 'title', 'desc'}
ATTRS = {'viewBox', 'width', 'height', 'fill', 'fill-rule', 'fill-opacity', 'clip-rule',
         'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
         'stroke-dasharray', 'stroke-dashoffset', 'stroke-opacity', 'opacity', 'd', 'x', 'y',
         'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'points', 'transform', 'id',
         'clip-path', 'mask', 'mask-type', 'maskUnits', 'maskContentUnits', 'clipPathUnits',
         'gradientUnits', 'gradientTransform', 'spreadMethod', 'offset', 'stop-color',
         'stop-opacity', 'fx', 'fy', 'fr', 'preserveAspectRatio', 'color',
         'shape-rendering', 'text-rendering', 'image-rendering'}
STYLE_ATTRS = {'fill', 'fill-rule', 'fill-opacity', 'clip-rule', 'stroke', 'stroke-width',
               'stroke-linecap', 'stroke-linejoin', 'stroke-opacity', 'opacity',
               'shape-rendering', 'text-rendering', 'image-rendering'}


def inline_svg_styles(root: ET.Element, brand: str) -> None:
    """Resolve only simple static paint classes; never retain a CSS stylesheet."""
    def declarations(text: str) -> dict[str, str]:
        if any(token in text for token in ('\\', '/*', '*/', '@', '{', '}')):
            raise ValueError(f'Unsupported SVG CSS: {brand}')
        result = {}
        for declaration in text.split(';'):
            if not declaration.strip():
                continue
            key, separator, value = declaration.partition(':')
            key, value = key.strip(), value.strip()
            if not separator or key not in STYLE_ATTRS or not value or '!important' in value:
                raise ValueError(f'Unsupported SVG paint declaration: {brand}')
            result[key] = value
        return result
    rules = []
    for parent in root.iter():
        for node in list(parent):
            if node.tag.removeprefix('{'+SVG_NS+'}') != 'style':
                continue
            text = node.text or ''
            if node.attrib or len(node):
                raise ValueError(f'Unsupported SVG stylesheet: {brand}')
            pattern = r'\.([a-zA-Z_][\w-]*)\s*\{([^{}]*)\}'
            for match in re.finditer(pattern, text):
                rules.append((match[1], declarations(match[2])))
            if re.sub(pattern, '', text).strip():
                raise ValueError(f'Only simple SVG paint classes allowed: {brand}')
            parent.remove(node)
    classes = {name for name, _ in rules}
    for node in root.iter():
        xml_space = node.attrib.pop('{http://www.w3.org/XML/1998/namespace}space', None)
        if xml_space not in (None, 'default', 'preserve'):
            raise ValueError(f'Unsupported SVG whitespace hint: {brand}')
        selected = node.attrib.pop('class', '').split()
        if any(name not in classes for name in selected):
            raise ValueError(f'Unknown SVG paint class: {brand}')
        for name, paint in rules:
            if name in selected:
                node.attrib.update(paint)
        if 'style' in node.attrib:
            node.attrib.update(declarations(node.attrib.pop('style')))


def checked_svg(body: str, brand: str) -> str:
    if len(body.encode()) > 100_000 or re.search(r'<!DOCTYPE|<!ENTITY|<\?', body, re.I):
        raise ValueError(f'Unsupported SVG document: {brand}')
    root = ET.fromstring(body)
    if root.tag not in ('svg', '{'+SVG_NS+'}svg') or 'viewBox' not in root.attrib:
        raise ValueError(f'SVG viewBox required: {brand}')
    inline_svg_styles(root, brand)
    ids = {node.attrib['id'] for node in root.iter() if 'id' in node.attrib}
    referenced_ids = {ref for node in root.iter() for value in node.attrib.values()
                      for ref in re.findall(r'url\(#([^)]*)\)', value)}
    for node in root.iter():
        tag = node.tag.removeprefix('{'+SVG_NS+'}')
        if tag not in TAGS:
            raise ValueError(f'Unsupported SVG element {tag}: {brand}')
        node.tag = tag
        for key, value in list(node.attrib.items()):
            if (key not in ATTRS or '\\' in value or '/*' in value or '*/' in value
                    or any(t in value.lower() for t in ['javascript:', 'data:', 'http:', 'https:', 'expression', '@import'])):
                raise ValueError(f'Unsupported SVG attribute {key}: {brand}')
            if re.search(r'url\s*\(', value, re.I):
                refs = re.findall(r'url\(#([a-zA-Z_][\w:.-]*)\)', value)
                if not refs or re.sub(r'url\(#[a-zA-Z_][\w:.-]*\)', '', value).strip() or any(ref not in ids for ref in refs):
                    raise ValueError(f'Only local SVG references allowed: {brand}')
                for ref in refs:
                    value = value.replace('url(#'+ref+')', 'url(#v99-'+brand+'-'+ref+')')
            if key == 'id':
                if not re.fullmatch(r'[a-zA-Z_][\w:.-]*', value):
                    if value in referenced_ids:
                        raise ValueError(f'Unsupported referenced SVG ID: {brand}')
                    # Design exports sometimes name an unused path «Fill 5».
                    # Remove only that unused label, preserving all geometry.
                    del node.attrib[key]
                    continue
                value = 'v99-'+brand+'-'+value
            node.attrib[key] = value
        if node.text and tag not in ('title', 'desc') and node.text.strip():
            raise ValueError(f'Unexpected SVG text: {brand}')
        node.tail = None
        if node.text is not None:
            node.text = node.text.strip() or None
    root.attrib.pop('width', None)
    root.attrib.pop('height', None)
    root.set('xmlns', SVG_NS)
    root.set('aria-hidden', 'true')
    root.set('focusable', 'false')
    return ET.tostring(root, encoding='unicode', short_empty_elements=True)


def compile_catalog() -> str:
    catalog = json.loads((ROOT/'tools/merchant_catalog.json').read_text())
    manifest = json.loads((ROOT/'tools/merchant_logos/manifest.json').read_text())
    brands, aliases = set(), {}
    for item in catalog:
        brand = item['brand']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', brand) or brand in brands:
            raise ValueError(f'Invalid or duplicate brand: {brand}')
        brands.add(brand)
        for value in [item['value'], *item['aliases']]:
            key = re.sub(r'[^\w]+', ' ', value.casefold().replace('ё', 'е')).strip()
            if key in aliases and aliases[key] != brand:
                raise ValueError(f'Ambiguous alias {value}: {brand}, {aliases[key]}')
            aliases[key] = brand
    logos = {}
    for brand, info in manifest.items():
        if brand not in brands:
            raise ValueError(f'Logo has no catalogue entry: {brand}')
        path = ROOT/'tools/merchant_logos'/info['file']
        if path.parent != ROOT/'tools/merchant_logos' or path.suffix not in ('.svg', '.png'):
            raise ValueError(f'Invalid logo path: {brand}')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != info['sha256']:
            raise ValueError(f'Logo source changed: {brand}')
        if not info.get('source_url', '').startswith('https://'):
            raise ValueError(f'Logo provenance required: {brand}')
        if path.suffix == '.svg':
            svg = checked_svg(raw.decode(), brand).encode()
            logos[brand] = '<img src="data:image/svg+xml;base64,'+base64.b64encode(svg).decode()+'" alt="" width="28" height="28" decoding="async">'
        else:
            if (not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > 300_000
                    or raw[12:16] != b'IHDR' or not all(0 < int.from_bytes(raw[start:start+4], 'big') <= 2048 for start in (16, 20))):
                raise ValueError(f'Expected a small PNG logo: {brand}')
            logos[brand] = '<img src="data:image/png;base64,'+base64.b64encode(raw).decode()+'" alt="" width="28" height="28" decoding="async">'
    dump = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return ('/* V99_MERCHANT_CATALOG_BEGIN — generated by tools/build_merchant_catalog.py */\n'
            +'const V96_MERCHANTS='+dump(catalog)+';\n'
            +'const V99_MERCHANT_LOGOS=Object.freeze('+dump(logos)+');\n'
            +'/* V99_MERCHANT_CATALOG_END */\n')


def build(check: bool = False) -> None:
    path = ROOT/'index.html'
    source = path.read_text()
    block = compile_catalog()
    pattern = r'/\* V99_MERCHANT_CATALOG_BEGIN.*?/\* V99_MERCHANT_CATALOG_END \*/\n'
    if not re.search(pattern, source, re.S):
        pattern = r'/\* Curated local aliases and brand-style marks; no vendor assets or remote lookups\. \*/\nconst V96_MERCHANTS=\[.*?\];\n'
    result, count = re.subn(pattern, lambda _: block, source, flags=re.S)
    if count != 1:
        raise ValueError('Expected exactly one merchant catalogue')
    if check:
        if result != source:
            raise ValueError('Embedded merchant catalogue is stale; run this builder')
    else:
        path.write_text(result)
    print('Merchant catalogue matches source' if check else 'Embedded local merchant catalogue and SVG logos')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    build(parser.parse_args().check)
