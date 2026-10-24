"""Writes frontend/src/odynza/odynza-dark.css and odynza-light.css: the Radar Night (dark) and Front Page (light,
the "Brief C" newspaper look) versions of every colour in the shared stylesheets, scoped to the Odynza site and its
theme. Run it again after changing frontend/src/styles/watch.css, studio.css, media.css, strategy.css or content.css:

    python scripts/odynza_dark_css.py
"""
import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['frontend/src/styles/studio.css', 'frontend/src/styles/media.css', 'frontend/src/styles/strategy.css', 'frontend/src/styles/content.css', 'frontend/src/styles/watch.css']
OUT = {'dark': ROOT / 'frontend/src/odynza/odynza-dark.css', 'light': ROOT / 'frontend/src/odynza/odynza-light.css'}
SCOPE = {'dark': ':where(body.odz:not(.odz-light)) .odz-scope', 'light': ':where(body.odz.odz-light) .odz-scope'}   # :where keeps the old specificity
PROPS = ('color', 'background', 'background-color', 'border', 'border-color', 'border-top', 'border-bottom',
         'border-left', 'border-right', 'border-top-color', 'border-bottom-color', 'outline', 'fill', 'stroke',
         'box-shadow', 'accent-color')
NAMED = {'white': '#ffffff', 'black': '#000000'}
INK, SOFT, MUTED = '#E8EEF8', '#B4C0D4', '#93A2BC'
SURFACES = ['#0F1830', '#131E38', '#18264A']
LINE = '#22325A'
LIME, CYAN, ORANGE, RED, GOOD = '#C6F432', '#4FD1E8', '#F5A35C', '#FF8A6B', '#8BE36B'
# Front Page (light): newsprint paper, navy ink, deeper accents that read on cream.
P_INK, P_SOFT, P_MUTED, P_WHITE = '#0A1020', '#3A4866', '#5E6880', '#FFFDF6'
P_SURFACES = ['#FFFDF6', '#F1ECDF', '#E8E1CF']
P_LINE, P_LINE_DARK = '#D3CAB3', '#8C846E'
P_OLIVE, P_ORANGE, P_RED, P_GOOD = '#4A6B00', '#B25E14', '#B93A2A', '#3F6E12'


def rgb(hex_):
    h = hex_.lstrip('#')
    if len(h) in (3, 4):
        h = ''.join(c * 2 for c in h[:3])
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def dark(hex_, role):
    """role: text | bg | line."""
    c = rgb(hex_)
    hue, light, sat = colorsys.rgb_to_hls(*c)
    y = lum(c)
    warm = sat > .35 and (hue < .12 or hue > .95)
    if role == 'line':
        return LINE if y > .5 else '#2E4170'
    if role == 'text':
        if warm and y < .55:
            return RED if hue < .05 or hue > .95 else ORANGE
        if sat > .25 and .2 < hue < .45 and y < .6:
            return GOOD if hue < .3 else LIME
        if y < .3:
            return INK
        if y < .55:
            return SOFT
        if y < .8:
            return MUTED
        return INK
    # background
    if sat > .45 and .25 < y < .8:
        return hex_                       # strong colours (score badges, accents) keep their colour
    if y >= .95:
        return SURFACES[0]
    if y >= .88:
        return SURFACES[1]
    if y >= .7:
        return SURFACES[2] if not warm else '#3A2A1C'
    if y < .25:
        return '#13203B'                  # dark green panels become navy
    return '#1D2B52'


def light(hex_, role):
    """The same roles for the light Front Page theme."""
    c = rgb(hex_)
    hue, _, sat = colorsys.rgb_to_hls(*c)
    y = lum(c)
    warm = sat > .35 and (hue < .12 or hue > .95)
    if role == 'line':
        return P_LINE if y > .5 else P_LINE_DARK
    if role == 'text':
        if warm and y < .55:
            return P_RED if hue < .05 or hue > .95 else P_ORANGE
        if sat > .25 and .2 < hue < .45 and y < .6:
            return P_GOOD if hue < .3 else P_OLIVE
        if y < .3:
            return P_INK
        if y < .55:
            return P_SOFT
        if y < .8:
            return P_MUTED
        return P_WHITE                    # light text sat on a dark or strong panel; those stay dark below
    if sat > .45 and .25 < y < .8:
        return hex_
    if y >= .95:
        return P_SURFACES[0]
    if y >= .88:
        return P_SURFACES[1]
    if y >= .7:
        return P_SURFACES[2] if not warm else '#F6E3CC'
    if y < .25:
        return P_INK                      # dark panels become the navy "opinion box"
    return '#DCD4BF'


HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:white|black)\b')


def convert(prop, value, mode='dark'):
    role = 'text' if prop in ('color', 'fill', 'accent-color') else 'line' if prop.startswith(('border', 'outline')) or prop == 'stroke' else 'bg'
    if prop == 'box-shadow':
        return re.sub(HEX, '#0006' if mode == 'dark' else '#0A10201A', value)

    def swap(m):
        v = NAMED.get(m.group(0).lower(), m.group(0))
        return (dark if mode == 'dark' else light)(v, role)
    return HEX.sub(swap, value)


def rules(css):
    """Yields (prefix, selector, body), keeping @media wrappers."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    i = 0
    while i < len(css):
        j = css.find('{', i)
        if j < 0:
            break
        head = css[i:j].strip()
        if head.startswith('@media'):
            depth, k = 1, j + 1
            while depth and k < len(css):
                depth += {'{': 1, '}': -1}.get(css[k], 0)
                k += 1
            for _, sel, body in rules(css[j + 1:k - 1]):
                yield head, sel, body
            i = k
            continue
        k = css.find('}', j)
        yield '', head, css[j + 1:k]
        i = k + 1


def scoped(selector, scope):
    out = []
    for s in selector.split(','):
        s = s.strip()
        if not s or s.startswith(('@', 'html', ':root', 'body', '*')) or 'keyframes' in s:
            continue
        out.append(f'{scope} {s}')
    return ','.join(out)


def main():
    for mode in ('dark', 'light'):
        blocks = []
        for name in SOURCES:
            for media, sel, body in rules((ROOT / name).read_text(encoding='utf-8')):
                decls = []
                for d in body.split(';'):
                    if ':' not in d:
                        continue
                    prop, value = (x.strip() for x in d.split(':', 1))
                    if prop.lower() in PROPS and HEX.search(value):
                        decls.append(f'{prop}:{convert(prop.lower(), value, mode)}')
                sel = scoped(sel, SCOPE[mode])
                if decls and sel:
                    rule = f'{sel}{{{";".join(decls)}}}'
                    blocks.append(f'{media}{{{rule}}}' if media else rule)
        OUT[mode].write_text('/* Generated by scripts/odynza_dark_css.py from ' + ', '.join(SOURCES) + '. Do not edit by hand. */\n'
                             + '\n'.join(blocks) + '\n', encoding='utf-8')
        print(f'{len(blocks)} rules -> {OUT[mode].relative_to(ROOT)}')


if __name__ == '__main__':
    main()
