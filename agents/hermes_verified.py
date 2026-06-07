"""
agents/hermes_verified.py — HERMES Verification Engine

HERMES is the only agent that verifies rather than discovers.

The Council's ARBITER flags specific URLs, filings, and records that need
verification. HERMES picks those up, checks them against live sources,
and produces Verified Intelligence Reports — the highest-confidence output
in the system because they are not inferred or synthesised but directly
confirmed from primary sources.

Verified briefs get their own tab in the UI. They are:
  - Specific: every claim has a source URL and access timestamp
  - Typed: Filing / CVE / Price / Regulatory / Deletion / API Change
  - Confidence: only CONFIRMED or VOID (either it checks out or it doesn't)
  - Actionable: each report includes the exact URL, the exact data point,
    and when it was last verified

This is the output that separates The Signal Society from every other
intelligence platform — we don't just surface signals, we verify them.
"""

import os, re, json, uuid, logging, requests, hashlib
from datetime import datetime, timedelta

try:
    from agents import llm_gateway
    HAS_GATEWAY = True
except ImportError:
    HAS_GATEWAY = False

log = logging.getLogger('HERMES_VERIFIED')

# ── VERIFICATION TYPES ────────────────────────────────────────────────────────
class VerificationType:
    SEC_FILING   = 'SEC_FILING'
    CVE          = 'CVE'
    PRICE_DATA   = 'PRICE_DATA'
    REGULATORY   = 'REGULATORY'
    DELETION     = 'DELETION'
    API_CHANGE   = 'API_CHANGE'
    PATENT       = 'PATENT'
    COURT_ORDER  = 'COURT_ORDER'
    GENERAL      = 'GENERAL'


# ── VERIFICATION RESULT SCHEMA ────────────────────────────────────────────────
def make_verified_report(
    queue_item:   str,
    source_id:    str,
    vtype:        str,
    confirmed:    bool,
    headline:     str,
    data:         dict,
    source_url:   str,
    evidence:     list,
    implications: str,
    action_items: list,
    tags:         list,
) -> dict:
    return {
        'id':           str(uuid.uuid4()),
        'type':         'verified_report',
        'citizen':      'HERMES',
        'timestamp':    datetime.utcnow().isoformat(),
        'verified_at':  datetime.utcnow().isoformat(),
        'queue_item':   queue_item,
        'source_id':    source_id,
        'vtype':        vtype,
        'confirmed':    confirmed,
        'confidence':   'CONFIRMED' if confirmed else 'VOID',
        'headline':     headline,
        'data':         data,
        'source_url':   source_url,
        'evidence':     evidence,
        'implications': implications,
        'action_items': action_items,
        'tags':         tags + ['#verified', '#hermes'],
        'reactions':    {'agree': 0, 'flag': 0, 'save': 0},
    }


# ── SOURCE VERIFIERS ──────────────────────────────────────────────────────────

class HermesVerifiedEngine:
    """
    Processes the HERMES verification queue and produces Verified Intelligence Reports.
    Each item in the queue is a specific URL, filing number, or data claim
    that the Council's ARBITER flagged as needing direct verification.
    """

    def __init__(self):
        self.log = logging.getLogger('HERMES_VERIFIED')
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SignalSociety/2.0 (verification)'})

    def process_queue(self, db) -> list:
        """
        Main entry point. Fetches pending queue items, verifies each,
        saves results, returns list of Verified Intelligence Reports.

        Queue items come from two sources:
        1. Council ARBITER posts (type='hermes_queue') — specific URLs/filings to verify
        2. HIGH/CONFIRMED briefs with action_items not yet processed by HERMES

        db.get_hermes_queue() handles both (added to database.py).
        """
        try:
            if hasattr(db, 'get_hermes_queue'):
                pending = db.get_hermes_queue()
            else:
                # Fallback: query posts directly if DB method missing
                self.log.warning('db.get_hermes_queue not found — using direct query')
                pending = db.get_posts(post_type='hermes_queue', limit=20) or []
        except Exception as e:
            self.log.error(f'Cannot fetch HERMES queue: {e}')
            return []

        if not pending:
            self.log.info('HERMES: no pending verification items')
            return []

        self.log.info(f'HERMES: processing {len(pending)} queue items')
        reports = []

        for item in pending[:6]:  # Max 6 verifications per run
            try:
                report = self._verify_item(item)
                if report:
                    db.save_post(report)
                    if hasattr(db, 'mark_hermes_item_processed'):
                        db.mark_hermes_item_processed(item.get('id',''))
                    else:
                        # Fallback: unpublish the queue post
                        try:
                            db.save_post({**item, 'published': False})
                        except Exception:
                            pass
                    reports.append(report)
                    self.log.info(
                        f"HERMES verified: {report['headline'][:60]} "
                        f"({'CONFIRMED' if report['confirmed'] else 'VOID'})"
                    )
                else:
                    if hasattr(db, 'mark_hermes_item_processed'):
                        db.mark_hermes_item_processed(item.get('id',''))
                    else:
                        # Fallback: unpublish the queue post
                        try:
                            db.save_post({**item, 'published': False})
                        except Exception:
                            pass
            except Exception as e:
                self.log.error(f"HERMES item {item.get('id','?')}: {e}")

        self.log.info(f'HERMES: produced {len(reports)} verification report(s)')
        return reports

    def _verify_item(self, item: dict) -> dict | None:
        """
        Route to the right verifier based on what the item looks like.
        Handles three item shapes:
          1. hermes_queue post: metadata.queue_items = list of strings
          2. Direct text reference: url_or_ref or text field
          3. Brief action_item: item is a brief dict with action_items list
        """
        # Shape 3: brief with action_items — process first action item
        if item.get('_hermes_source') == 'brief':
            action_items = item.get('action_items') or []
            if isinstance(action_items, str):
                import json as _j
                try: action_items = _j.loads(action_items)
                except Exception: action_items = [action_items]
            if not action_items:
                return None
            url_or_ref = action_items[0] if action_items else ''
            source_id  = item.get('id', '')
        else:
            # Shape 1: queue post with metadata.queue_items
            meta = item.get('metadata') or item.get('raw_data') or {}
            if isinstance(meta, str):
                import json as _j
                try: meta = _j.loads(meta)
                except Exception: meta = {}
            queue_items = meta.get('queue_items') or []
            if queue_items:
                url_or_ref = queue_items[0]
            else:
                # Shape 2: direct text reference
                url_or_ref = item.get('url_or_ref') or item.get('text', '') or item.get('body', '')
            source_id  = item.get('source_id', '') or item.get('id', '')

        if not url_or_ref:
            return None

        text_lower = url_or_ref.lower()

        # Route to specific verifier
        if re.search(r'sec\.gov|edgar|accession|form\s*(4|8-k|s-1|sc\s*13)', text_lower):
            return self._verify_sec(url_or_ref, source_id, item)

        if re.search(r'cve-\d{4}-\d+|nvd\.nist\.gov|cisa\.gov/kev', text_lower):
            return self._verify_cve(url_or_ref, source_id, item)

        if re.search(r'federalregister\.gov|federal register|docket|cfr\s*part', text_lower):
            return self._verify_regulatory(url_or_ref, source_id, item)

        if re.search(r'patents\.google|patentsview|uspto|patent\s*(number|no\.?)\s*us', text_lower):
            return self._verify_patent(url_or_ref, source_id, item)

        if re.search(r'wayback|archive\.org|deleted|removed|404|no longer available', text_lower):
            return self._verify_deletion(url_or_ref, source_id, item)

        if re.search(r'changelog|deprecated|api\s*v\d|breaking change|sunset|end.of.life', text_lower):
            return self._verify_api_change(url_or_ref, source_id, item)

        if re.search(r'courtlistener|pacer|court|case\s*no|docket\s*no', text_lower):
            return self._verify_court(url_or_ref, source_id, item)

        # Generic URL verification
        if url_or_ref.startswith('http'):
            return self._verify_generic_url(url_or_ref, source_id, item)

        # LLM-assisted verification for text-only claims
        return self._verify_with_llm(url_or_ref, source_id, item)

    # ── SPECIFIC VERIFIERS ─────────────────────────────────────────────────────

    def _verify_sec(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify an SEC filing via EDGAR full-text search."""
        # Extract accession number if present
        acc_match = re.search(r'(\d{10}-\d{2}-\d{6}|\d{18})', ref.replace('-', ''))
        form_match = re.search(r'form\s*(4|8-K|S-1|SC\s*13[DG]|424B4)', ref, re.IGNORECASE)
        company    = item.get('entity') or item.get('company') or ''

        acc_num  = acc_match.group(0) if acc_match else ''
        form_type = form_match.group(1).upper() if form_match else ''

        try:
            # Try EDGAR full-text search
            search_query = company or form_type or ref[:50]
            resp = self.session.get(
                'https://efts.sec.gov/LATEST/search-index',
                params={
                    'q':              f'"{search_query}"',
                    'dateRange':      'custom',
                    'startdt':        (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'),
                    'enddt':          datetime.utcnow().strftime('%Y-%m-%d'),
                    'forms':          form_type or '8-K',
                },
                timeout=10,
            )
            confirmed = False
            data      = {}
            url       = ''

            if resp.ok:
                hits = resp.json().get('hits', {}).get('hits', [])
                if hits:
                    hit   = hits[0]['_source']
                    confirmed = True
                    url   = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum=&type={form_type}&dateb=&owner=include&count=10&search_text="
                    data  = {
                        'filing_type':    hit.get('form_type', form_type),
                        'entity_name':    hit.get('entity_name', company),
                        'filed_date':     hit.get('file_date', ''),
                        'accession':      hit.get('accession_no', acc_num),
                        'description':    (hit.get('period_of_report') or '')[:100],
                    }

            return make_verified_report(
                queue_item   = ref,
                source_id    = source_id,
                vtype        = VerificationType.SEC_FILING,
                confirmed    = confirmed,
                headline     = f"SEC {form_type or 'Filing'}: {company or 'entity'} — {'CONFIRMED' if confirmed else 'NOT FOUND'}",
                data         = data,
                source_url   = url or f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&dateb=&owner=include&count=10',
                evidence     = [
                    {
                        'claim': f"Filing {form_type} exists for {company}" if confirmed else f"Filing {form_type} not found for {company}",
                        'tag':   'VERIFIED' if confirmed else 'VOID',
                        'source': f'SEC EDGAR — verified {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                    }
                ],
                implications = f"{'Filing confirmed — original signal corroborated.' if confirmed else 'Filing not found — original signal may be inaccurate or premature.'}",
                action_items = [f"Review full filing at {url}"] if confirmed else ["Re-check source — filing not found in EDGAR"],
                tags         = ['#SEC', '#EDGAR', f'#{form_type}' if form_type else '#filing'],
            )
        except Exception as e:
            self.log.error(f'SEC verify ({ref[:40]}): {e}')
            return None

    def _verify_cve(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify a CVE via NVD and CISA KEV."""
        cve_match = re.search(r'CVE-\d{4}-\d+', ref, re.IGNORECASE)
        if not cve_match:
            return None
        cve_id = cve_match.group(0).upper()

        confirmed   = False
        data        = {}
        is_kev      = False
        cvss        = 0.0
        vendor      = ''
        description = ''
        url         = f'https://nvd.nist.gov/vuln/detail/{cve_id}'

        try:
            # Check NVD
            resp = self.session.get(
                f'https://services.nvd.nist.gov/rest/json/cves/2.0',
                params={'cveId': cve_id},
                timeout=12,
            )
            if resp.ok:
                vulns = resp.json().get('vulnerabilities', [])
                if vulns:
                    confirmed   = True
                    cve_data    = vulns[0].get('cve', {})
                    descs       = cve_data.get('descriptions', [])
                    description = next((d['value'] for d in descs if d.get('lang') == 'en'), '')[:300]
                    metrics     = cve_data.get('metrics', {})
                    for key in ('cvssMetricV31', 'cvssMetricV30', 'cvssMetricV2'):
                        if key in metrics and metrics[key]:
                            cvss = metrics[key][0].get('cvssData', {}).get('baseScore', 0)
                            break
                    data = {
                        'cve_id':      cve_id,
                        'cvss_score':  cvss,
                        'description': description,
                        'published':   cve_data.get('published', ''),
                    }
        except Exception as e:
            self.log.error(f'NVD verify ({cve_id}): {e}')

        # Check CISA KEV
        try:
            kev_resp = self.session.get(
                'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
                timeout=12,
            )
            if kev_resp.ok:
                vulns_kev = kev_resp.json().get('vulnerabilities', [])
                for v in vulns_kev:
                    if v.get('cveID', '').upper() == cve_id:
                        is_kev = True
                        vendor = v.get('vendorProject', '')
                        data.update({
                            'is_actively_exploited': True,
                            'vendor':                vendor,
                            'product':               v.get('product', ''),
                            'required_action':       v.get('requiredAction', ''),
                            'due_date':              v.get('dueDate', ''),
                        })
                        break
        except Exception as e:
            self.log.error(f'CISA KEV verify ({cve_id}): {e}')

        severity = 'CRITICAL' if cvss >= 9.0 else 'HIGH' if cvss >= 7.0 else 'MEDIUM' if cvss >= 4.0 else 'LOW'

        evidence_items = [
            {'claim': f'{cve_id} confirmed in NVD with CVSS {cvss}', 'tag': 'VERIFIED', 'source': f'NVD — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC'},
        ]
        if is_kev:
            evidence_items.append({
                'claim': f'{cve_id} is on CISA Known Exploited Vulnerabilities list — actively exploited in the wild',
                'tag':   'VERIFIED',
                'source': f'CISA KEV — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
            })

        return make_verified_report(
            queue_item   = ref,
            source_id    = source_id,
            vtype        = VerificationType.CVE,
            confirmed    = confirmed,
            headline     = f"{cve_id} ({severity}, CVSS {cvss}) — {'ACTIVELY EXPLOITED' if is_kev else 'VERIFIED IN NVD' if confirmed else 'NOT FOUND'}",
            data         = data,
            source_url   = url,
            evidence     = evidence_items,
            implications = (
                f"{'CRITICAL: Actively exploited. Patch immediately.' if is_kev else ''}"
                f"CVSS {cvss} — {severity} severity. "
                f"Affects: {vendor or 'unknown vendor'}. {description[:150]}"
            ),
            action_items = (
                ['Apply patch immediately — CISA KEV confirms active exploitation'] if is_kev
                else [f'Check vendor advisory for {vendor}', f'Apply CVSS {cvss} patch per severity timeline']
            ),
            tags = ['#CVE', '#security', f'#{severity}', '#CISA' if is_kev else '#NVD'],
        )

    def _verify_regulatory(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify a Federal Register docket or rule."""
        doc_match = re.search(r'(\d{4}-\d{5,6})', ref)
        doc_num   = doc_match.group(1) if doc_match else ''

        try:
            params = {'fields[]': ['title','document_number','abstract','publication_date',
                                   'html_url','type','comment_date','significant']}
            if doc_num:
                params['conditions[docket_id]'] = doc_num
            else:
                # Search by text from ref
                params['conditions[term]']                   = ref[:80]
                params['conditions[publication_date][gte]']  = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
                params['per_page']                            = 3

            resp = self.session.get(
                'https://www.federalregister.gov/api/v1/articles.json',
                params=params,
                timeout=12,
            )
            confirmed = False
            data      = {}
            url       = ''

            if resp.ok:
                results = resp.json().get('results', [])
                if results:
                    r         = results[0]
                    confirmed = True
                    url       = r.get('html_url', '')
                    pub_date  = r.get('publication_date', '')
                    comm_date = r.get('comment_date', '')
                    # Calculate comment period
                    comment_days = 999
                    if pub_date and comm_date:
                        try:
                            pd = datetime.strptime(pub_date[:10], '%Y-%m-%d')
                            cd = datetime.strptime(comm_date[:10], '%Y-%m-%d')
                            comment_days = (cd - pd).days
                        except Exception:
                            pass
                    # Burial indicator: Friday + short comment period
                    try:
                        pub_dt    = datetime.strptime(pub_date[:10], '%Y-%m-%d')
                        is_friday = pub_dt.weekday() == 4
                    except Exception:
                        is_friday = False

                    data = {
                        'document_number': r.get('document_number', doc_num),
                        'title':           r.get('title', ''),
                        'type':            r.get('type', ''),
                        'publication_date': pub_date,
                        'comment_date':    comm_date,
                        'comment_days':    comment_days,
                        'is_significant':  r.get('significant', False),
                        'is_friday_burial': is_friday and comment_days < 21,
                    }

            burial_flag = data.get('is_friday_burial', False)
            return make_verified_report(
                queue_item   = ref,
                source_id    = source_id,
                vtype        = VerificationType.REGULATORY,
                confirmed    = confirmed,
                headline     = (
                    f"{'⚠ BURIAL INDICATOR: ' if burial_flag else ''}"
                    f"Federal Register {data.get('document_number', doc_num)}: "
                    f"{'CONFIRMED' if confirmed else 'NOT FOUND'}"
                    + (f" — {data.get('comment_days','')}d comment period" if confirmed else '')
                ),
                data         = data,
                source_url   = url,
                evidence     = [
                    {
                        'claim':  f"Rule published {data.get('publication_date','')} with {data.get('comment_days','')} day comment period",
                        'tag':    'VERIFIED' if confirmed else 'VOID',
                        'source': f'Federal Register API — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                    },
                    *([{
                        'claim':  f"Published on Friday with {data.get('comment_days','')} day comment period — standard burial pattern",
                        'tag':    'VERIFIED',
                        'source': 'Pattern: Friday late-day publication with short comment window',
                    }] if burial_flag else []),
                ],
                implications = (
                    f"{'BURIAL INDICATOR: High-impact rule published Friday with <21 day comment period. ' if burial_flag else ''}"
                    f"Rule type: {data.get('type','')}. "
                    f"{'Significant rule per Federal Register designation.' if data.get('is_significant') else ''}"
                ),
                action_items = [
                    f"Read full rule at {url}",
                    f"File comment before {data.get('comment_date','deadline')}",
                ] if confirmed else ['Docket not found — verify document number'],
                tags = ['#federalregister', '#regulation', '#burial' if burial_flag else '#rule'],
            )
        except Exception as e:
            self.log.error(f'Regulatory verify ({ref[:40]}): {e}')
            return None

    def _verify_patent(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify a patent via PatentsView."""
        pnum_match = re.search(r'US\s*(\d{7,8})', ref, re.IGNORECASE)
        pnum       = pnum_match.group(1) if pnum_match else ''

        if not pnum:
            return None

        try:
            resp = self.session.post(
                'https://search.patentsview.org/api/v1/patent/',
                json={
                    'q': {'patent_number': pnum},
                    'f': ['patent_number','patent_title','patent_abstract',
                          'patent_date','assignee_organization','cpc_group_id'],
                },
                headers={'Content-Type': 'application/json'},
                timeout=12,
            )
            confirmed = False
            data      = {}

            if resp.ok:
                patents = resp.json().get('patents') or []
                if patents:
                    p         = patents[0]
                    confirmed = True
                    assignees = [a.get('assignee_organization','') for a in (p.get('assignees') or []) if a.get('assignee_organization')]
                    cpcs      = [c.get('cpc_group_id','') for c in (p.get('cpcs') or [])]
                    data = {
                        'patent_number': pnum,
                        'title':         p.get('patent_title',''),
                        'assignee':      assignees[0] if assignees else '',
                        'patent_date':   p.get('patent_date',''),
                        'cpc_class':     cpcs[0] if cpcs else '',
                        'abstract':      (p.get('patent_abstract') or '')[:200],
                    }

            return make_verified_report(
                queue_item   = ref,
                source_id    = source_id,
                vtype        = VerificationType.PATENT,
                confirmed    = confirmed,
                headline     = f"US{pnum}: {'CONFIRMED' if confirmed else 'NOT FOUND'}" + (f" — {data.get('assignee','')}" if confirmed else ''),
                data         = data,
                source_url   = f'https://patents.google.com/patent/US{pnum}',
                evidence     = [{
                    'claim':  f"Patent US{pnum} granted to {data.get('assignee','')} on {data.get('patent_date','')}" if confirmed else f"Patent US{pnum} not found in PatentsView",
                    'tag':    'VERIFIED' if confirmed else 'VOID',
                    'source': f'USPTO PatentsView — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                }],
                implications = f"Patent {pnum} {'confirmed. Assignee: ' + data.get('assignee','') + '. Technology: ' + data.get('cpc_class','') if confirmed else 'not found — check patent number.'}",
                action_items = [f"Review full patent at https://patents.google.com/patent/US{pnum}"] if confirmed else ['Verify patent number'],
                tags         = ['#patents', '#USPTO', '#IP'],
            )
        except Exception as e:
            self.log.error(f'Patent verify (US{pnum}): {e}')
            return None

    def _verify_deletion(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify a claimed deletion via Wayback Machine."""
        # Extract URL from the reference
        url_match = re.search(r'https?://[^\s"\'<>]+', ref)
        target_url = url_match.group(0) if url_match else ''
        if not target_url:
            return None

        confirmed    = False
        was_live     = False
        now_gone     = False
        archive_url  = ''
        data         = {}

        try:
            # Check Wayback availability (was it ever live?)
            avail_resp = self.session.get(
                'https://archive.org/wayback/available',
                params={'url': target_url},
                timeout=10,
            )
            if avail_resp.ok:
                snap = avail_resp.json().get('archived_snapshots', {}).get('closest', {})
                if snap:
                    was_live    = snap.get('status') == '200'
                    archive_url = snap.get('url', '')

            # Check current live status
            try:
                live_resp = self.session.head(target_url, timeout=6, allow_redirects=True)
                now_gone  = live_resp.status_code in (404, 403, 410, 451)
                data['current_status'] = live_resp.status_code
            except Exception:
                now_gone = True
                data['current_status'] = 'unreachable'

            confirmed = was_live and now_gone
            data.update({
                'target_url':   target_url,
                'was_live':     was_live,
                'now_gone':     now_gone,
                'archive_url':  archive_url,
            })
        except Exception as e:
            self.log.error(f'Deletion verify ({target_url[:40]}): {e}')

        return make_verified_report(
            queue_item   = ref,
            source_id    = source_id,
            vtype        = VerificationType.DELETION,
            confirmed    = confirmed,
            headline     = f"{'CONFIRMED DELETION' if confirmed else 'Deletion unconfirmed'}: {target_url[:60]}",
            data         = data,
            source_url   = archive_url or f'https://web.archive.org/web/*/{target_url}',
            evidence     = [
                {
                    'claim':  f"URL previously accessible (Wayback: {archive_url[:60]})" if was_live else "No Wayback record found",
                    'tag':    'VERIFIED' if was_live else 'INFERRED',
                    'source': f'Wayback Machine — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                },
                {
                    'claim':  f"URL now returns {data.get('current_status','404')} — confirmed removal" if now_gone else "URL still accessible",
                    'tag':    'VERIFIED',
                    'source': f'Direct HTTP check — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                },
            ],
            implications = (
                f"{'Page confirmed deleted. Was accessible, now returns ' + str(data.get('current_status','')) + '.' if confirmed else 'Deletion not confirmed — page may still be accessible or was never indexed.'} "
                f"{'Archived version available at ' + archive_url[:60] if archive_url else ''}"
            ),
            action_items = (
                [f"Review archived version: {archive_url}", "Investigate reason for removal"] if confirmed
                else ["Deletion not confirmed — verify URL manually"]
            ),
            tags         = ['#deletion', '#wayback', '#echo'],
        )

    def _verify_api_change(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify an API changelog entry or deprecation notice."""
        # Try to fetch the changelog URL directly
        url_match = re.search(r'https?://[^\s"\'<>]+', ref)
        changelog_url = url_match.group(0) if url_match else ''

        confirmed   = False
        data        = {}
        is_breaking = False

        if changelog_url:
            try:
                resp = self.session.get(changelog_url, timeout=10)
                if resp.ok:
                    content     = resp.text[:3000]
                    confirmed   = True
                    breaking_kws = ['breaking', 'deprecated', 'removed', 'sunset',
                                    'end of life', 'migration required', 'incompatible']
                    is_breaking = any(kw in content.lower() for kw in breaking_kws)
                    # Extract version number if present
                    ver_match = re.search(r'v\d+\.\d+[\.\d]*', content)
                    data = {
                        'url':         changelog_url,
                        'is_breaking': is_breaking,
                        'version':     ver_match.group(0) if ver_match else '',
                        'content_hash': hashlib.md5(content.encode()).hexdigest()[:8],
                        'fetched_at':  datetime.utcnow().isoformat(),
                    }
            except Exception as e:
                self.log.error(f'API change verify ({changelog_url[:40]}): {e}')

        return make_verified_report(
            queue_item   = ref,
            source_id    = source_id,
            vtype        = VerificationType.API_CHANGE,
            confirmed    = confirmed,
            headline     = (
                f"{'⚠ BREAKING CHANGE CONFIRMED' if is_breaking and confirmed else 'API Change'}: "
                f"{changelog_url[:50] if changelog_url else ref[:50]}"
            ),
            data         = data,
            source_url   = changelog_url or '',
            evidence     = [{
                'claim':  f"Changelog accessed at {changelog_url}" + (' — breaking change confirmed' if is_breaking else '') if confirmed else "Changelog URL not accessible",
                'tag':    'VERIFIED' if confirmed else 'VOID',
                'source': f'Direct fetch — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
            }],
            implications = (
                f"{'BREAKING: Migration required. ' if is_breaking else ''}"
                f"{'Version: ' + data.get('version','') + '. ' if data.get('version') else ''}"
                f"{'Verified at source.' if confirmed else 'Could not verify — check URL manually.'}"
            ),
            action_items = (
                [f"Review breaking change at {changelog_url}", "Update integration before deprecated version sunset"]
                if is_breaking and confirmed
                else [f"Monitor {changelog_url} for changes"] if confirmed
                else ["Verify changelog URL manually"]
            ),
            tags         = ['#changelog', '#API', '#hermes', '#breaking' if is_breaking else '#update'],
        )

    def _verify_court(self, ref: str, source_id: str, item: dict) -> dict | None:
        """Verify a court document via CourtListener."""
        try:
            # Extract case name or docket number
            docket_match = re.search(r'(\d{2}-[a-z]{2}-\d+|\d{2}-\d+)', ref, re.IGNORECASE)
            search_term  = docket_match.group(0) if docket_match else ref[:60]

            resp = self.session.get(
                'https://www.courtlistener.com/api/rest/v3/opinions/',
                params={
                    'q':        search_term,
                    'order_by': '-score',
                    'page_size': 3,
                    'format':   'json',
                },
                headers={'Accept': 'application/json'},
                timeout=12,
            )
            confirmed = False
            data      = {}
            url       = ''

            if resp.ok:
                results = resp.json().get('results', [])
                if results:
                    r         = results[0]
                    confirmed = True
                    url       = f"https://www.courtlistener.com{r.get('absolute_url','')}"
                    data = {
                        'case_name':   r.get('case_name',''),
                        'court':       r.get('court_id',''),
                        'date_filed':  r.get('date_filed',''),
                        'url':         url,
                    }

            return make_verified_report(
                queue_item   = ref,
                source_id    = source_id,
                vtype        = VerificationType.COURT_ORDER,
                confirmed    = confirmed,
                headline     = f"Court document: {data.get('case_name', search_term)[:60]} — {'CONFIRMED' if confirmed else 'NOT FOUND'}",
                data         = data,
                source_url   = url,
                evidence     = [{
                    'claim':  f"Court opinion found: {data.get('case_name','')} ({data.get('court','')}, {data.get('date_filed','')})" if confirmed else "Court document not found in CourtListener",
                    'tag':    'VERIFIED' if confirmed else 'VOID',
                    'source': f'CourtListener — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                }],
                implications = f"{'Court ruling confirmed. Review at ' + url if confirmed else 'Document not found — verify docket number.'}",
                action_items = [f"Review full opinion at {url}"] if confirmed else ["Verify court and docket number manually"],
                tags         = ['#court', '#legal', '#courtlistener'],
            )
        except Exception as e:
            self.log.error(f'Court verify ({ref[:40]}): {e}')
            return None

    def _verify_generic_url(self, url: str, source_id: str, item: dict) -> dict | None:
        """Verify any URL is still live and accessible."""
        try:
            resp      = self.session.head(url, timeout=8, allow_redirects=True)
            confirmed = resp.status_code < 400
            return make_verified_report(
                queue_item   = url,
                source_id    = source_id,
                vtype        = VerificationType.GENERAL,
                confirmed    = confirmed,
                headline     = f"URL {'accessible' if confirmed else 'inaccessible'}: {url[:70]}",
                data         = {'url': url, 'status_code': resp.status_code, 'final_url': resp.url},
                source_url   = url,
                evidence     = [{
                    'claim':  f"HTTP {resp.status_code} — {'accessible' if confirmed else 'not accessible'}",
                    'tag':    'VERIFIED',
                    'source': f'Direct HTTP check — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                }],
                implications = f"URL {'confirmed live at time of verification.' if confirmed else 'not accessible — content may have been removed.'}",
                action_items = [f"Access URL: {url}"] if confirmed else ["URL inaccessible — check Wayback Machine for archived version"],
                tags         = ['#verification', '#url'],
            )
        except Exception as e:
            self.log.error(f'Generic URL verify ({url[:40]}): {e}')
            return None

    def _verify_with_llm(self, claim: str, source_id: str, item: dict) -> dict | None:
        """
        For text-only claims that cannot be directly verified via API,
        use LLM to assess verifiability and produce a structured assessment.
        """
        if not HAS_GATEWAY:
            return None

        system = """You are HERMES in verification mode.
A Council debate flagged this claim for verification. You cannot verify it via
direct API access. Produce a structured assessment of verifiability.
Return ONLY valid JSON:
{
  "verifiable": true/false,
  "method": "how to verify this claim",
  "confidence": "LOW/MEDIUM/HIGH",
  "assessment": "1-2 sentences on what is known vs unknown about this claim",
  "source_suggestions": ["specific URL or database to check"]
}"""

        raw = llm_gateway.call(
            agent         = 'COUNCIL',
            system_prompt = system,
            user_prompt   = f"Claim to assess: {claim}",
            max_tokens    = 200,
            temperature   = 0.3,
        )
        if not raw:
            return None

        parsed = {}
        try:
            clean  = raw.replace('```json','').replace('```','').strip()
            parsed = json.loads(clean)
        except Exception:
            pass

        assessment = parsed.get('assessment', claim[:150])
        return make_verified_report(
            queue_item   = claim,
            source_id    = source_id,
            vtype        = VerificationType.GENERAL,
            confirmed    = False,  # LLM assessment is not verification
            headline     = f"Verification assessment: {claim[:60]}",
            data         = parsed,
            source_url   = '',
            evidence     = [{
                'claim':  assessment,
                'tag':    'INFERRED',
                'source': f'HERMES LLM assessment — not direct verification',
            }],
            implications = f"Claim requires manual verification via: {', '.join(parsed.get('source_suggestions', ['primary source'])[:2])}",
            action_items = parsed.get('source_suggestions', ['Verify manually']) [:3],
            tags         = ['#unverified', '#assessment'],
        )


# ── SINGLETON ─────────────────────────────────────────────────────────────────
hermes_engine = HermesVerifiedEngine()
