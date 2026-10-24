"""The weekly Competitor Brief (the Odynza Radar "mission debrief") as HTML (in-app, email body and PDF) and the Monday email over SMTP."""
from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from api.pdf import render_pdf

# The "mission debrief" look Odynza picked for Odynza Radar: navy page, lime/cyan/orange signals, mono labels.
NAVY, CARD, LINE, INK, SOFT, MUTED = '#0A1020', '#111A30', '#22304F', '#E8EEF9', '#C7D2E6', '#93A2BC'
LIME, CYAN, ORANGE, RED = '#C6F432', '#4FD1E8', '#F5A35C', '#FF8A6B'
HEAD = "'Space Grotesk','Segoe UI',Arial,sans-serif"
BODY = "'IBM Plex Sans','Segoe UI',Arial,sans-serif"
MONO = "'IBM Plex Mono',Consolas,'Courier New',monospace"
BLIPS = [CYAN, ORANGE, RED, '#B79CFF', '#7EE0A1', '#F7D154']
SCORE = {5: (RED, NAVY), 4: (ORANGE, NAVY), 3: (CYAN, NAVY), 2: (LINE, INK), 1: (LINE, MUTED)}
PLATFORM = {'instagram': 'Instagram', 'facebook': 'Facebook', 'linkedin': 'LinkedIn'}


def _num(v, pct=False):
    if v is None:
        return '—'
    return f'{v:.2f}%' if pct else f'{v:,}'


def _mono(text: str, colour: str = MUTED, size: int = 11) -> str:
    return (f'<span style="font-family:{MONO};font-size:{size}px;letter-spacing:1.4px;color:{colour}">'
            f'{escape(text)}</span>')


def _card(body: str, title: str = '') -> str:
    return (f'<div style="background:{CARD};border:1px solid {LINE};border-radius:16px;padding:18px 20px;margin-top:16px;break-inside:avoid;page-break-inside:avoid">'
            + (f'<div style="font-family:{HEAD};font-size:17px;font-weight:700;color:{INK};margin-bottom:12px">'
               f'{escape(title)}</div>' if title else '') + body + '</div>')


def activity(r: dict) -> int:
    """How loud a rival was this week: posts and ads count most, then news and hiring (same as the app's radar)."""
    return (r.get('posts_7d') or 0) * 3 + (r.get('live_ads') or 0) * 4 + (r.get('news') or 0) + (1 if r.get('jobs') else 0)


def status(brief: dict) -> tuple[str, str]:
    top = max([int(i.get('score') or 0) for i in brief.get('items') or []], default=0)
    if top >= 5:
        return 'RED ALERT', RED
    if top >= 4:
        return 'CONTACTS INBOUND', ORANGE
    if brief.get('items'):
        return 'LIGHT TRAFFIC', CYAN
    return 'QUIET SKIES', LIME


def _placed(rivals: list[dict]) -> list[dict]:
    import math
    top = max([activity(r) for r in rivals] + [1])
    out = []
    shown = rivals[:8]
    for i, r in enumerate(shown):
        a = activity(r) / top
        radius = 58 + (1 - a) * 66
        angle = -2.2 + i * 2 * math.pi / max(len(shown), 1)
        out.append({'r': r, 'x': 200 + math.cos(angle) * radius, 'y': 150 + math.sin(angle) * radius,
                    'colour': BLIPS[i % len(BLIPS)], 'ring': 'CLOSE' if a > 0.66 else 'MID' if a > 0.33 else 'FAR'})
    return out


def radar_svg(rivals: list[dict]) -> str:
    """Rivals on a radar, louder ones nearer the centre. SVG, so it shows on the page and in the PDF, not in email."""
    dots = ''.join(
        f'<circle cx="{d["x"]:.0f}" cy="{d["y"]:.0f}" r="16" fill="{d["colour"]}" fill-opacity=".18"/>'
        f'<circle cx="{d["x"]:.0f}" cy="{d["y"]:.0f}" r="7" fill="{d["colour"]}"/>'
        f'<text x="{d["x"] + (-14 if d["x"] < 200 else 14):.0f}" y="{d["y"] - 14:.0f}" '
        f'text-anchor="{"end" if d["x"] < 200 else "start"}" font-family="Arial" font-size="13" fill="{INK}">'
        f'{escape(d["r"]["name"])}</text>' for d in _placed(rivals))
    rings = ''.join(f'<circle cx="200" cy="150" r="{r}" fill="none" stroke="{LINE}" stroke-width="1.5"/>' for r in (130, 86, 42))
    return (f'<svg viewBox="0 0 400 300" width="100%" style="display:block;max-width:300px;margin:0 auto">{rings}'
            f'<path d="M70 150 H330 M200 20 V280" stroke="#1A2642"/>'
            f'<path d="M200 150 L312 84 A130 130 0 0 0 200 20 Z" fill="{LIME}" fill-opacity=".14"/>'
            f'<path d="M200 150 L312 84" stroke="{LIME}" stroke-width="2.5" stroke-linecap="round"/>'
            f'<circle cx="200" cy="150" r="7" fill="{LIME}"/>'
            f'<text x="200" y="176" text-anchor="middle" font-family="Arial" font-size="12" fill="{INK}">You</text>{dots}</svg>'
            f'<div style="text-align:center;font-size:11px;color:{MUTED};margin-top:6px">Closer to the centre means more active this week</div>')


def snapshot_html(snap: dict) -> str:
    """The market this week, from the captures (no AI): field notes, you vs rivals, contact log, intercepted, paid signals."""
    e = lambda v: escape(str(v or ''))
    out = []
    if snap.get('takeaways'):
        lis = ''.join(f'<li style="margin:0 0 6px">{e(t)}</li>' for t in snap['takeaways'])
        out.append(_card(f'<ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.55;color:{INK}">{lis}</ul>', 'Field notes'))
    rows = [s for s in snap.get('standing') or [] if s.get('you') is not None or s.get('rivals_avg') is not None]
    if rows:
        bars = []
        for s in rows:
            top = max(s.get('you') or 0, s.get('rivals_avg') or 0) or 1
            you_w = max(2, round((s.get('you') or 0) / top * 100))
            them_w = max(2, round((s.get('rivals_avg') or 0) / top * 100))
            ahead = (s.get('you') or 0) >= (s.get('rivals_avg') or 0)
            best = f' · best: {e(s.get("leader"))} {_num(s.get("leader_rate"), True)}' if s.get('leader') else ''
            bars.append(
                f'<table role="presentation" style="width:100%;border-collapse:collapse;font-size:13px;color:{INK}">'
                f'<tr><td>{PLATFORM.get(s["platform"], s["platform"])} · you</td><td style="text-align:right;font-weight:700;'
                f'color:{LIME if ahead else RED}">{_num(s.get("you"), True)}</td></tr></table>'
                f'<div style="height:8px;border-radius:4px;background:{LIME};width:{you_w}%;margin:5px 0 7px"></div>'
                f'<table role="presentation" style="width:100%;border-collapse:collapse;font-size:13px;color:{MUTED}">'
                f'<tr><td>Rivals\' average{best}</td><td style="text-align:right;font-weight:700">{_num(s.get("rivals_avg"), True)}</td></tr></table>'
                f'<div style="height:8px;border-radius:4px;background:{CYAN};width:{them_w}%;margin:5px 0 16px"></div>')
        out.append(_card(''.join(bars) + f'<div style="font-size:11px;color:{MUTED}">Engagement rate: interactions per post '
                         'divided by followers.</div>', 'You against the rivals'))
    if snap.get('rivals'):
        log = []
        for d in sorted(_placed(snap['rivals']), key=lambda d: -activity(d['r'])):
            r = d['r']
            facts = ', '.join(x for x in [
                f'{r["posts_7d"]} post{"s" if r["posts_7d"] != 1 else ""}' if r.get('posts_7d') else 'no posts',
                f'{r["news"]} news mention{"s" if r["news"] != 1 else ""}' if r.get('news') else '',
                f'hiring {r["jobs"]} roles' if r.get('jobs') else '',
                f'{r["live_ads"]} live ad{"s" if r["live_ads"] != 1 else ""}' if r.get('live_ads') else '',
                f'{_num(r["followers"])} on {PLATFORM.get(r.get("platform"), "")}' if r.get('followers') and r.get('platform') else '',
            ] if x)
            log.append(f'<tr><td style="width:18px;padding:10px 0;border-bottom:1px solid {LINE};vertical-align:top">'
                       f'<div style="width:12px;height:12px;border-radius:6px;background:{d["colour"]};margin-top:4px"></div></td>'
                       f'<td style="padding:10px 8px;border-bottom:1px solid {LINE}"><b style="font-size:15px;color:{INK}">{e(r["name"])}</b>'
                       f' <span style="font-size:11px;color:{MUTED}">{e(r.get("tier"))}</span>'
                       f'<div style="font-size:12px;color:{SOFT}">{e(facts)}</div></td>'
                       f'<td style="padding:10px 0;border-bottom:1px solid {LINE};text-align:right">{_mono(d["ring"], d["colour"], 12)}</td></tr>')
        out.append(_card(f'<table role="presentation" style="width:100%;border-collapse:collapse">{"".join(log)}</table>', 'Contact log'))
    cards = [(f'{p["company"]} · {PLATFORM.get(p["platform"], "")}' + (f' · {str(p.get("date"))[:10]}' if p.get('date') else ''),
              p.get('caption') or 'Post without a caption',
              f'{_num(p.get("likes"))} likes · {_num(p.get("comments"))} comments' + (' · this week' if p.get('this_week') else ''),
              p.get('url'), CYAN) for p in snap.get('posts') or []]
    cards += [(' · '.join(x for x in (n.get('company'), n.get('site'), str(n.get('date') or '')[:10]) if x),
               n.get('title') or n.get('site') or 'Link', 'News mention' if n.get('kind') == 'news' else 'Web mention',
               n.get('url'), ORANGE) for n in snap.get('news') or []]
    if cards:
        blocks = ''.join(
            f'<div style="border-bottom:1px solid {LINE};padding:10px 0">{_mono(tag.upper(), colour)}'
            f'<div dir="auto" style="font-size:14px;line-height:1.5;color:{INK};margin:4px 0">{e(text[:280])}</div>'
            f'<div style="font-size:12px;color:{MUTED}">{e(foot)}'
            + (f' · <a style="color:{LIME}" href="{e(url)}">open</a>' if url else '') + '</div></div>'
            for tag, text, foot, url, colour in cards[:6])
        out.append(_card(blocks, 'Intercepted this week'))
    if snap.get('ads'):
        ads = ''.join(
            f'<div style="padding:8px 0;border-bottom:1px solid {LINE}"><b style="color:{INK}">{e(a["company"])}</b> '
            f'<span dir="auto" style="color:{SOFT}">{e(a.get("headline") or a.get("body") or "Ad")}</span>'
            f'<div style="font-size:12px;color:{MUTED}">live since {e(a.get("start"))} · '
            f'<a style="color:{LIME}" href="{e(a.get("url"))}">Ad Library</a></div></div>' for a in snap['ads'])
    elif (snap.get('numbers') or {}).get('live_ads') is None:
        ads = f'<div style="font-size:14px;color:{SOFT}">Ads have not been checked yet.</div>'
    else:
        ads = f'<div style="font-size:14px;color:{SOFT}">No watched rival runs ads in Egypt right now. The paid space is open.</div>'
    out.append(_card(ads, 'Paid signals'))
    return ''.join(out)


def brief_html(client_name: str, brief: dict, standalone=True, snapshot: dict | None = None, radar=True) -> str:
    """The weekly brief as a mission debrief. Inline styles and tables, so the same markup works in Gmail, the
    browser and the PDF; radar=False leaves out the SVG radar, which email clients do not show."""
    e = lambda v: escape(str(v or ''))
    items = brief.get('items') or []
    quiet = brief.get('quiet') or not items
    head = brief.get('headline') or ('No big moves on the radar.' if quiet else 'Rivals moved this week.')
    code, tone = status(brief)
    snap = snapshot or {}
    n = snap.get('numbers') or {}
    issue = f'DEBRIEF {int(brief.get("id") or 0):03d} · ' if brief.get('id') else ''
    parts = [f'<div style="font-family:{BODY};color:{INK};background:{NAVY};max-width:760px;margin:0 auto;padding:26px 28px;border-radius:18px">',
             '<table role="presentation" style="width:100%;border-collapse:collapse;border-bottom:1px solid ' + LINE + '"><tr>'
             f'<td style="padding-bottom:12px"><span style="display:inline-block;width:20px;height:20px;border:4px solid {LIME};'
             f'border-radius:50%;vertical-align:middle;box-sizing:border-box"></span> '
             f'<b style="font-family:{HEAD};font-size:19px;color:{INK};vertical-align:middle">odynza</b> '
             f'<span style="font-size:9px;letter-spacing:2px;font-weight:700;background:{LIME};color:{NAVY};border-radius:5px;'
             f'padding:2px 6px;vertical-align:middle">RADAR</span></td>'
             f'<td style="padding-bottom:12px;text-align:right">{_mono(f"{issue}WEEK OF {brief.get("week_start")}", SOFT)}</td></tr></table>',
             f'<div style="margin-top:22px">{_mono("STATUS: " + code, tone, 12)}</div>'
             f'<h1 style="font-family:{HEAD};font-size:34px;line-height:1.08;letter-spacing:-1px;margin:10px 0 8px;color:{INK}">{e(head)}</h1>'
             f'<div style="font-size:15px;line-height:1.6;color:{SOFT}">{e(client_name)} · '
             + (f'{len(items)} move{"s" if len(items) != 1 else ""} worth your attention, scored 1 to 5 against your profile.'
                if not quiet else 'No rival change scored 3 or more this week. Here is what the market did instead.') + '</div>']
    if radar and snap.get('rivals'):
        parts.append(f'<div style="background:{CARD};border:1px solid {LINE};border-radius:16px;padding:14px;margin-top:18px">'
                     f'{radar_svg(snap["rivals"])}</div>')
    if n:
        tiles = [('CONTACTS', _num(n.get('rivals')), 'rivals on watch'), ('TRANSMISSIONS', _num(n.get('posts_7d')), 'rival posts in 7 days'),
                 ('PAID SIGNALS', _num(n.get('live_ads')), 'live ads found' if n.get('live_ads') is not None else 'not checked yet'),
                 ('CHATTER', _num(n.get('news')), 'news and web mentions')]
        cells = ''.join(f'<td style="width:25%;padding:4px"><div style="background:{CARD};border:1px solid {LINE};border-radius:14px;'
                        f'padding:12px 14px">{_mono(k, MUTED, 10)}<div style="font-family:{HEAD};font-size:30px;font-weight:700;'
                        f'color:{INK};line-height:1.2">{v}</div><div style="font-size:11px;color:{MUTED}">{escape(note)}</div></div></td>'
                        for k, v, note in tiles)
        parts.append(f'<table role="presentation" style="width:100%;border-collapse:collapse;margin-top:16px"><tr>{cells}</tr></table>')
    if items:
        cards = []
        for i_n, i in enumerate(items, 1):
            score = int(i.get('score') or 3)
            bg, fg = SCORE.get(score, SCORE[3])
            cards.append(
                f'<table role="presentation" style="width:100%;border-collapse:collapse;border-bottom:1px solid {LINE};margin-bottom:6px"><tr>'
                f'<td style="width:52px;vertical-align:top;padding:10px 0"><div style="width:40px;height:40px;border-radius:10px;background:{bg};'
                f'color:{fg};font-family:{HEAD};font-weight:700;font-size:20px;text-align:center;line-height:40px">{score}</div></td>'
                f'<td style="vertical-align:top;padding:10px 0">'
                f'{_mono(f"{i_n:02d} · {str(i.get("competitor") or "").upper()} · {str(i.get("type") or "").upper()}")}'
                f'<div dir="auto" style="font-family:{HEAD};font-size:16px;font-weight:700;margin:4px 0 6px;color:{INK}">{e(i.get("title"))}</div>'
                f'<div style="font-size:14px;margin-bottom:6px;line-height:1.5;color:{SOFT}"><b style="color:{INK}">What it means for you.</b> {e(i.get("meaning"))}</div>'
                + (f'<div style="font-size:14px;line-height:1.5;background:#1A2A1C;border-left:3px solid {LIME};border-radius:6px;'
                   f'padding:8px 10px;margin-bottom:6px;color:{INK}"><b>Your move.</b> {e(i.get("move"))}</div>' if i.get('move') else '')
                + f'<div style="font-size:12px;color:{MUTED}">Source: <a style="color:{LIME}" href="{e(i.get("source_url"))}">'
                f'{e(i.get("source_url"))}</a> · captured {e(str(i.get("captured_at") or "")[:16].replace("T", " "))}</div>'
                '</td></tr></table>')
        parts.append(_card(''.join(cards), 'Priority contacts'))
    if snapshot:
        parts.append(snapshot_html(snapshot))
    moves = [i for i in items if i.get('move')][:3]
    nxt = ''.join(f'<div style="padding:6px 0"><b style="color:{INK}">{e(m.get("competitor"))}:</b> '
                  f'<span style="color:{SOFT}">{e(m.get("move"))}</span></div>' for m in moves)
    nxt += (f'<div style="padding:6px 0;color:{SOFT}"><b style="color:{LIME}">M0</b> Pick an opportunity from this week\'s watch. '
            f'<b style="color:{CYAN}">M1</b> Plan a response. <b style="color:{ORANGE}">M2</b> Make the posts. All in Odynza Radar.</div>')
    parts.append(f'<div style="background:#16224A;border:1px solid #2A3A5C;border-radius:16px;padding:18px 20px;margin-top:16px;break-inside:avoid;page-break-inside:avoid">'
                 f'{_mono("NEXT MOVES", LIME, 12)}<div style="margin-top:8px;font-size:14px;line-height:1.5">{nxt}</div></div>')
    as_of = f' · DATA AS OF {str(snap.get("as_of") or "")[:16].replace("T", " ")} UTC' if snap.get('as_of') else ''
    parts.append(f'<div style="border-top:1px solid {LINE};margin-top:18px;padding-top:12px">'
                 f'{_mono("ODYNZA RADAR · WATCH. PLAN. CREATE. BEFORE THEY DO." + as_of, MUTED, 10)}'
                 f'<div style="font-size:11px;color:{MUTED};margin-top:6px">Scores: 5 act this week · 4 plan a response · '
                 '3 worth knowing · 2 note · 1 archive. Every move links to the page capture it came from.</div></div></div>')
    body = ''.join(parts)
    if not standalone:
        return body
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Odynza Radar debrief</title>'
            f'<style>@page{{size:A4;margin:0}}html{{background:{NAVY}}}body{{margin:0;padding:10mm 8mm;background:{NAVY};'
            '-webkit-print-color-adjust:exact;print-color-adjust:exact}</style></head><body>' + body + '</body></html>')


async def brief_pdf(client_name: str, brief: dict, snapshot: dict | None = None) -> bytes:
    return await asyncio.to_thread(render_pdf, brief_html(client_name, brief, snapshot=snapshot))


def email_settings() -> dict:
    to = [a.strip() for a in (os.getenv('BRIEF_EMAIL_TO') or '').split(',') if a.strip()]
    user = (os.getenv('SMTP_USER') or '').strip()
    return {'host': (os.getenv('SMTP_HOST') or 'smtp.gmail.com').strip(), 'port': int(os.getenv('SMTP_PORT') or 587),
            'user': user, 'password': (os.getenv('SMTP_PASSWORD') or '').replace(' ', '').strip(),
            'sender': (os.getenv('SMTP_FROM') or user).strip(), 'to': to}


def email_ready() -> bool:
    s = email_settings()
    return bool(s['user'] and s['password'])


def send_brief_email(client_name: str, brief: dict, pdf: bytes | None, recipients: list[str],
                     snapshot: dict | None = None) -> None:
    """Blocking; call through asyncio.to_thread. Raises RuntimeError with a plain reason."""
    s = email_settings()
    to = list(dict.fromkeys(recipients + s['to']))
    if not s['user'] or not s['password']:
        raise RuntimeError('Email is not set up. Add SMTP_USER and SMTP_PASSWORD (a Gmail app password) to .env.')
    if not to:
        raise RuntimeError('No one to send to. Add BRIEF_EMAIL_TO to .env or an address in Watch settings.')
    msg = EmailMessage()
    msg['Subject'] = f"Odynza Radar debrief · {brief.get('week_start')} · {brief.get('headline') or 'Quiet week'}"
    msg['From'] = s['sender']
    msg['To'] = ', '.join(to)
    lines = [brief.get('headline') or 'Quiet week', '']
    for i in brief.get('items') or []:
        lines += [f"[{i.get('score')}] {i.get('title')}", f"What it means for you: {i.get('meaning')}",
                  f"Source: {i.get('source_url')}", '']
    for t in (snapshot or {}).get('takeaways') or []:
        lines.append(f'- {t}')
    msg.set_content('\n'.join(lines) or 'Quiet week.')
    msg.add_alternative(brief_html(client_name, brief, snapshot=snapshot, radar=False), subtype='html')
    if pdf:
        msg.add_attachment(pdf, maintype='application', subtype='pdf',
                           filename=f"competitor-brief-{brief.get('week_start')}.pdf")
    try:
        with smtplib.SMTP(s['host'], s['port'], timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(s['user'], s['password'])
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError('The mail server refused the login. For Gmail use an app password, not your normal password.') from None
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f'The email could not be sent ({type(exc).__name__}). Check SMTP_HOST and the internet connection.') from None
