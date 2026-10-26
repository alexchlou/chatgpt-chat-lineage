"""Evidence-bounded daily HTML brief from verified local metadata; no I/O writes."""
from collections import Counter
from datetime import datetime
import hashlib
import html
import json
import re
from zoneinfo import ZoneInfo

VERSION = '2.0.0'
TIERS = {'E0': 'Exact tag overlap', 'E1': 'Metadata compatibility', 'H': 'Pending hypothesis'}
COLORS = {'E0': '#23664b', 'E1': '#1b6480', 'H': '#875b13'}
STATES = {'RENAMED': 'Renamed', 'ALREADY CORRECT': 'Kept title', 'BLOCKED': 'Blocked',
          'VERIFICATION FAILED': 'Verification failed'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def local_date(value, timezone='UTC'):
    try:
        t = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return t.astimezone(ZoneInfo(timezone)).date().isoformat() if t.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def cross(edge):
    return edge.get('properties', {}).get('layer') == 'cross_topic'


def daily_delta(updates, relations, event_date, update_id, timezone='UTC'):
    """Calendar-day export additions, excluding the initial graph baseline.

    First introduction, not observed_at, determines the export day. Reappearance
    and code-only exports never become new research relations. Counts refer only
    to currently active cross-topic relations; removed/all-layer IDs stay separate.
    """
    if not updates or updates[-1]['update_id'] != update_id:
        raise ValueError('Graph update history does not match committed manifest')
    by_id = {e['id']: e for e in relations}
    seen, new, baseline, changed, removed = set(), set(), set(), set(), set()
    missing_times = 0
    for pos, u in enumerate(updates):
        day = local_date(u.get('exported_at'), timezone)
        if day is None:
            missing_times += 1
        introduced = set(u.get('added', [])) - seen
        if day == event_date:
            (baseline if pos == 0 else new).update(introduced)
            changed.update(u.get('changed', []))
            removed.update(u.get('removed', []))
        seen.update(u.get('added', []))
    active = lambda ids: [by_id[i] for i in sorted(ids) if i in by_id and
                         cross(by_id[i]) and by_id[i]['properties'].get('active')]
    additions = active(new)
    return {'scope': timezone + ' calendar date of graph export, not observation or browser-run time',
            'event_date': event_date, 'as_of_update_id': update_id,
            'added': additions, 'added_counts': dict(Counter(e['properties']['tier'] for e in additions)),
            'baseline_cross_topic_count': len(active(baseline)),
            'changed_cross_topic_ids': sorted(i for i in changed if i in by_id and cross(by_id[i])),
            'removed_all_layer_ids': sorted(removed), 'missing_export_times': missing_times,
            'not_displayed_addition_ids': sorted(new - {e['id'] for e in additions})}


def candidate_brief(asset, graph, relations, target_urls):
    nodes = {n['id']: n for n in graph['nodes']}
    valid, stale = [], []
    for original in asset.get('candidates', []):
        ids = original.get('support_observation_ids', [])
        fingerprints = original.get('support_fingerprints', {})
        if (not ids or set(ids) != set(fingerprints) or
                any(i not in nodes or digest(nodes[i]['properties']) != fingerprints[i] for i in ids)):
            stale.append(original['id'])
            continue
        urls = sorted({nodes[i]['properties']['conversation_url'] for i in ids})
        related = [e for e in relations if cross(e) and e['properties'].get('active') and
                   {nodes[e['source']]['properties'].get('url'),
                    nodes[e['target']]['properties'].get('url')} <= set(urls)]
        # The candidate is always a hypothesis even if some supporting metadata
        # edges carry E0/E1. Neither fresh observations nor mail can promote it.
        c = dict(original, tier='H', validation_status='PENDING_VALIDATION',
                 support_urls=urls, matches_this_run=sorted(set(urls) & set(target_urls)),
                 relation_evidence=[{'id': e['id'], 'registry_id': e['properties'].get('registry_id'),
                                     'tier': e['properties']['tier']} for e in related],
                 candidate_source_ref=asset.get('source_ref'),
                 candidate_source_sha256=asset.get('source_sha256'))
        valid.append(c)
    order = {'verify_first': 0, 'conditional': 1, 'exploratory': 2}
    valid.sort(key=lambda c: (-len(c['matches_this_run']), order.get(c.get('priority'), 3), c['id']))
    return {'candidates': valid, 'shown_ids': [c['id'] for c in valid[:3]], 'stale_ids': stale,
            'selection': 'up to three existing candidates, run URL overlap then prior audit order; not a novelty ranking',
            'asset_sha256': digest(asset)}


def build_brief(summary, graph, relations, updates, candidates):
    delta = daily_delta(updates, relations, summary['event_date'], summary['graph_update_id'], summary.get('timezone', 'UTC'))
    papers = candidate_brief(candidates, graph, relations, [t['conversation_url'] for t in summary['targets']])
    issues = []
    if summary['run_state'] != 'COMPLETE':
        issues.append('Run state: ' + summary['run_state'] + '; this is not complete.')
    if summary['frozen_count'] < summary['requested_count']:
        issues.append(f"Requested {summary['requested_count']}; frozen {summary['frozen_count']}.")
    unresolved = [t for t in summary['targets'] if t['status'] not in {'RENAMED', 'ALREADY CORRECT'}]
    for t in unresolved:
        issues.append(f"Target {t['position']}: {t['status']}; " + str(t.get('rationale') or 'Reason not recorded; consult the attached state.'))
    if len(summary['targets']) < summary['frozen_count']:
        issues.append('Some frozen targets lack a result; observed titles must not be invented.')
    for t in summary['targets']:
        if t['status'] in {'RENAMED', 'ALREADY CORRECT'}:
            verification = t.get('verification') or {}
            if (not t.get('displayed_title') or any(verification.get(k) is not True for k in
                    ['address_url_matches', 'document_url_matches', 'sidebar_title_matches', 'editor_closed'])):
                issues.append(f"Target {t['position']} has incomplete verification fields; preserve the record without inventing evidence.")
    if summary['stale_research_relations']:
        issues.append(f"{summary['stale_research_relations']} relations have changed sources and are quarantined.")
    if papers['stale_ids']:
        issues.append('Candidate source fingerprints changed or are missing; withheld: ' + ', '.join(papers['stale_ids']))
    if delta['missing_export_times']:
        issues.append('Some graph exports lack timezone-aware timestamps and cannot count as daily additions.')
    return {'body_version': VERSION, 'run_id': summary['run_id'], 'event_date': summary['event_date'],
            'graph_delta': delta, 'papers': papers, 'issues': issues,
            'limitations': summary.get('limitations', []),
            'cumulative_relation_counts': summary['research_relation_counts']}


def esc(v):
    return html.escape('Unknown' if v is None else str(v), quote=True)


def chat_link(url, text):
    # Source titles and URLs are data, never HTML, image loads or mail actions.
    if isinstance(url, str) and re.fullmatch(r'https://chatgpt\.com/c/[a-f0-9-]+', url):
        return f'<a href="{esc(url)}" style="color:#155e75;text-decoration:underline">{esc(text)}</a>'
    return esc(text)


def badge(tier):
    return f'<span style="color:{COLORS.get(tier,"#334155")};font-weight:700">{esc(tier)} · {esc(TIERS.get(tier,tier))}</span>'


def section(title, content):
    return f'<h2 style="font-size:19px;margin:30px 0 12px;color:#123f4b">{title}</h2>{content}'


def card(content, color='#dce5e9'):
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 16px;margin:10px 0;background:#ffffff">{content}</div>'


def endpoint_link(node, support):
    url = node['properties'].get('url')
    titles = sorted({s['displayed_title'] for s in support
                     if s.get('conversation_url') == url and s.get('displayed_title')})
    # A same-day ambiguous graph label must not hide the actual source title or
    # invent ordering between observations. Show titles pinned to this relation.
    label = ' / '.join(titles) + ' (title at source observation)' if titles else node['label']
    return chat_link(url, label)


def render(summary, brief, graph, delivery_key, sample=False):
    nodes = {n['id']: n for n in graph['nodes']}
    counts, delta = summary['status_counts'], brief['graph_delta']
    zone = summary.get('timezone', 'UTC')
    failed = sum(v for k, v in counts.items() if k not in {'RENAMED', 'ALREADY CORRECT'})
    metrics = ''.join(f'<td style="padding:12px;text-align:center"><strong style="font-size:26px">{n}</strong><br>{label}</td>'
                      for n, label in [(summary['frozen_count'], 'Frozen'), (counts.get('RENAMED', 0), 'Renamed'),
                                       (counts.get('ALREADY CORRECT', 0), 'Kept'), (failed, 'Needs attention')])
    header = f'<div style="background:#123f4b;color:white;padding:24px;border-radius:8px"><small>CHATGPT CHAT LINEAGE</small><h1 style="font-size:25px">{esc(summary["event_date"])} Naming and Research Report</h1><p>{esc(zone)} · {esc(summary["run_state"])} · {"Preview validation" if sample else "Daily archive"}</p></div>'
    header += f'<p>Run: {esc(summary["run_id"])}<br>Source: {esc(summary["source_type"])}; requested {summary["requested_count"]}; recorded results {len(summary["targets"])}.</p>'
    if sample:
        header += card('This explicitly requested preview reuses an existing run. It does not rerun naming or replace the original archived report.', '#d0b16b')
    header += '<table role="presentation" width="100%"><tr>' + metrics + '</tr></table>'
    rows = []
    for t in summary['targets']:
        actual = chat_link(t['conversation_url'], t.get('displayed_title') or 'Observed title unknown')
        titles = '<strong>' + actual + '</strong>'
        titles += '<br><small>Original: ' + esc(t['original_title']) + '<br>Proposed: ' + esc(t.get('proposed_title')) + '</small>'
        rows.append(f'<tr><td>{t["position"]}</td><td>{esc(t["status"])}</td><td style="overflow-wrap:anywhere">{titles}</td></tr>')
    results = section('01 Naming results', '<p>Observed titles come from the recorded run, not a new browser check.</p><table width="100%" cellspacing="0" cellpadding="8" style="table-layout:fixed;font-size:13px"><colgroup><col style="width:32px"><col style="width:132px"><col></colgroup><thead><tr><th>#</th><th>Status</th><th>Observed title and naming decision</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')
    totals = ', '.join(f'{tier}: {summary["research_relation_counts"].get(tier, 0)}' for tier in TIERS)
    rels = f'<p><strong>{len(delta["added"])} daily additions</strong>. Cumulative active relations: {totals}.</p>'
    rels += f'<p>Calendar: {esc(zone)} {esc(summary["event_date"])}; committed exports through this snapshot, deduplicated by relation ID. These are not exclusive to this run. Initial baseline: {delta["baseline_cross_topic_count"]}, reported separately from additions.</p>'
    rels += '<p>E0: exact recorded tag overlap. E1: metadata compatibility. H: pending hypothesis. E0/E1 do not establish common arguments, causality, or research conclusions.</p>'
    for e in delta['added']:
        p = e['properties']; support = p.get('support', [])
        endpoints = ' ↔ '.join(endpoint_link(nodes[e[k]], support) for k in ['source', 'target'])
        types = ', '.join(sorted({s['source_type'] for s in support})) or 'Not recorded'
        observations = ', '.join(s['observation_id'] for s in support)
        rels += card(f'{badge(p["tier"])}<h3>{esc(p["label"])}</h3><p>{endpoints}</p><p>Basis: {esc(p.get("evidence"))}<br>Needs validation: {esc(p.get("validation_needed"))}</p><small>Relation: {esc(p.get("registry_id") or e["id"])}<br>Source types: {esc(types)}<br>Observation: {esc(observations)}<br>Full refs, URLs, event IDs, and fingerprints: mail-brief.json in the ZIP.</small>', COLORS[p['tier']])
    if not delta['added']:
        rels += card('No active cross-topic additions beyond the initial baseline were recorded for this date. No relationships are invented to fill the report.')
    rels += f'<p>Changed cross-topic IDs: {len(delta["changed_cross_topic_ids"])}; removed records (all layers): {len(delta["removed_all_layer_ids"])}; quarantined sources: {summary["stale_research_relations"]}.</p>'
    papers = brief['papers']; shown = papers['candidates'][:3]
    candidates = f'<p>{len(shown)} of {len(papers["candidates"])} existing valid candidates shown, ordered by overlap with this run and prior coding order. All remain H / PENDING_VALIDATION, not a claim of novelty or publication readiness.</p>'
    for c in shown:
        detail = f'{badge("H")} · {esc(c["id"])}<h3>{esc(c["title"])}</h3>'
        for label, key in [('Research question','rq'),('Existing metadata support','existing_support'),('Pending inference','hypothesis'),('Required materials','needed'),('Narrowing or stop condition','stop_condition')]:
            detail += f'<p><strong>{label}:</strong> {esc(c[key])}</p>'
        detail += f'<small>{len(c["support_observation_ids"])} fingerprinted observations; {len(c["matches_this_run"])} URLs overlap this run. Full provenance is in the attachments.</small>'
        candidates += card(detail, '#d0b16b')
    if not shown:
        candidates += card('No registered candidates currently have valid supporting fingerprints. Additional materials are needed; no paper topic is inferred automatically.')
    issues = '<ul>' + ''.join('<li>' + esc(x) + '</li>' for x in brief['issues']) + '</ul>' if brief['issues'] else '<p>No blocks, verification gaps, changed sources, or missing denominators are recorded in this run.</p>'
    issues += '<p>Limits: naming metadata only; some UI metrics may be incomplete. Historical sources retain their provenance. Generating this email is not a new browser verification. Complete limitations remain in run-summary.json.</p>'
    attachments = section('05 Complete attachments', '<p><strong>report.pdf</strong>: previewable graph and run results.<br><strong>report-bundle.zip</strong>: full offline interactive HTML, run CSV, summary, structured brief, and SHA-256 inventory.</p>')
    footer = f'<p style="font-size:11px;overflow-wrap:anywhere">Delivery key: {esc(delivery_key)}<br>Graph snapshot: {esc(summary["graph_update_id"])}<br>Body template: {VERSION}. Explicit previews use a separate stable deduplication scope; daily runs must never use that scope as a retry bypass.</p>'
    body = header + results + section('02 Graph additions and evidence tiers', rels) + section('03 Integrative paper candidates', candidates) + section('04 Anomalies and limitations', issues) + attachments + footer
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Naming and Research Report</title></head><body style="background:#f1f5f6;color:#263d49;font-family:Arial,sans-serif;line-height:1.6"><table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="760" style="width:100%;max-width:760px;background:white"><tr><td style="padding:22px;overflow-wrap:anywhere">' + body + '</td></tr></table></td></tr></table></body></html>'
