"""
agents/cassandra.py — CASSANDRA, The Scenario Analyst
Territory: Internal signal synthesis → scenario analysis

Improvements v2:
  - _build_prompt() condensed from 300+ tokens to ~120 — major token saving
  - Gate: only activates when ≥3 signals with SIL score ≥65 exist
  - SIL scores passed into prompt — confidence weighted by signal quality
  - _match_historical_pattern() now requires 3+ data points (not keyword-only)
  - MAX_THINK_CALLS_PER_RUN = 2 (scenarios are expensive — quality over quantity)
  - Cooldown: 6h between runs (was 2h — scenarios need more signal accumulation)
  - On-demand trigger preserved for high-quality convergence events
"""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta

log = logging.getLogger('CASSANDRA')


class CassandraAgent:
    """
    CASSANDRA does NOT inherit BaseAgent — she reads internal signals,
    not external APIs. She is the meta-analyst, synthesising what other
    agents have found into forward-looking scenarios.
    """
    name      = 'CASSANDRA'
    title     = 'The Scenario Analyst'
    color     = '#6366F1'
    territory = 'Internal Signal Synthesis'
    tagline   = 'I tell you what will happen. You choose whether to listen.'

    MAX_THINK_CALLS_PER_RUN = 2

    # Minimum signals with minimum SIL quality to trigger analysis
    MIN_SIGNALS          = 3
    MIN_SIL_SCORE        = 65
    COOLDOWN_HOURS       = 6

    # Topic clusters for scenario grouping
    TOPIC_CLUSTERS = {
        'ai_governance':     ['ai', 'artificial intelligence', 'llm', 'regulation', 'policy', 'openai', 'anthropic'],
        'financial_stress':  ['market', 'crash', 'yield', 'inflation', 'fed', 'recession', 'credit', 'debt'],
        'infrastructure':    ['infrastructure', 'grid', 'pipeline', 'datacenter', 'spectrum', 'fcc', 'permit'],
        'supply_chain':      ['shipping', 'commodity', 'supply', 'port', 'bdi', 'iron ore', 'semiconductor'],
        'cyber_kinetic':     ['breach', 'vulnerability', 'ransomware', 'cisa', 'cve', 'attack', 'exploit'],
        'geopolitical':      ['military', 'conflict', 'sanctions', 'trade war', 'election', 'coup', 'treaty'],
        'bio_health':        ['pandemic', 'outbreak', 'who', 'pathogen', 'vaccine', 'fda', 'clinical'],
        'capital_flows':     ['btc', 'crypto', 'treasury', 'forex', 'fund', 'vc', 'acquisition', 'ipo'],
    }

    # Historical scenario templates
    SCENARIO_TEMPLATES = [
        {
            'name':        'Pre-announcement convergence',
            'keywords':    ['hiring', 'patent', 'fcc', 'experimental', 'acquisition', 'regulatory'],
            'precedent':   'Amazon AWS launch (preceded by 18 months of infrastructure filings), iPhone launch (FCC experimental license)',
            'template':    'Multiple regulatory/IP/hiring signals converging on same entity before public announcement.',
        },
        {
            'name':        'Financial-physical divergence',
            'keywords':    ['market', 'boom', 'investment', 'iron ore', 'shipping', 'bdi', 'commodity'],
            'precedent':   '2007-08 credit crisis (financial assets rising while physical indicators contracted)',
            'template':    'Capital markets pricing in growth while physical supply chain data contracts.',
        },
        {
            'name':        'Narrative-data divergence',
            'keywords':    ['narrative', 'media', 'coverage', 'gdelt', 'tone', 'sentiment', 'story'],
            'precedent':   'SVB collapse (positive media narrative until 72 hours before bank run)',
            'template':    'Official/media narrative diverges from primary source data.',
        },
        {
            'name':        'Quiet regulatory burial',
            'keywords':    ['friday', 'comment period', 'federal register', 'rule', 'regulation', '15-day', '21-day'],
            'precedent':   'Net neutrality rollback (published Friday before holiday weekend)',
            'template':    'High-impact regulatory change buried with minimal comment period or adverse timing.',
        },
        {
            'name':        'Supply chain precursor cascade',
            'keywords':    ['port', 'vessel', 'commodity', 'manufacturing', 'inventory', 'lead time'],
            'precedent':   '2021 semiconductor shortage (visible in vessel AIS 6 months before mainstream coverage)',
            'template':    'Physical bottleneck signals accumulating upstream before consumer/market awareness.',
        },
    ]

    def run(self, db=None):
        """
        CASSANDRA's run: reads recent high-quality signals from DB,
        clusters them by topic, generates forward-looking scenarios.
        """
        if db is None:
            try:
                from database import db as _db
                db = _db
            except Exception as e:
                log.error(f'CASSANDRA: no DB access: {e}')
                return []

        # Cooldown check
        try:
            last_run = db.get_last_agent_run(self.name)
            if last_run:
                hours_since = (datetime.utcnow() - last_run).total_seconds() / 3600
                if hours_since < self.COOLDOWN_HOURS:
                    log.info(f'CASSANDRA: cooldown active ({hours_since:.1f}h < {self.COOLDOWN_HOURS}h)')
                    return []
        except Exception:
            pass

        # Fetch recent high-quality signals
        try:
            all_posts = db.get_posts(limit=60) or []
        except Exception as e:
            log.error(f'CASSANDRA fetch posts: {e}')
            return []

        # Filter to high-SIL signals only
        high_quality = []
        for p in all_posts:
            sil_score = p.get('sil_score', 0) or p.get('metadata', {}).get('sil_score', 0)
            if sil_score >= self.MIN_SIL_SCORE or p.get('type') in ('signal_alert', 'town_hall'):
                high_quality.append(p)

        if len(high_quality) < self.MIN_SIGNALS:
            log.info(f'CASSANDRA: only {len(high_quality)} high-quality signals (min {self.MIN_SIGNALS}) — skipping')
            return []

        log.info(f'CASSANDRA: {len(high_quality)} high-quality signals — analysing')

        # Cluster by topic
        clusters = self._cluster_signals(high_quality)
        if not clusters:
            log.info('CASSANDRA: no clear topic clusters — skipping')
            return []

        # Generate scenarios for top clusters
        posts        = []
        groq_calls   = 0

        for topic, signals in sorted(clusters.items(), key=lambda x: -len(x[1]))[:self.MAX_THINK_CALLS_PER_RUN]:
            if groq_calls >= self.MAX_THINK_CALLS_PER_RUN:
                break
            if len(signals) < 2:
                continue
            try:
                scenario = self._generate_scenario(topic, signals)
                if scenario:
                    posts.append(scenario)
                    groq_calls += 1
                    try:
                        db.save_post(scenario)
                    except Exception as e:
                        log.error(f'CASSANDRA save: {e}')
            except Exception as e:
                log.error(f'CASSANDRA scenario ({topic}): {e}')

        if posts:
            try:
                db.log_agent_run(self.name, len(posts))
            except Exception:
                pass

        log.info(f'CASSANDRA: produced {len(posts)} scenario(s)')
        return posts

    def _cluster_signals(self, signals: list) -> dict:
        """Group signals by topic cluster using keyword matching."""
        from collections import defaultdict
        clusters = defaultdict(list)
        for signal in signals:
            text = (
                (signal.get('body') or '') + ' ' +
                (signal.get('headline') or '') + ' ' +
                ' '.join(signal.get('tags') or [])
            ).lower()
            best_cluster = None
            best_score   = 0
            for cluster_name, keywords in self.TOPIC_CLUSTERS.items():
                score = sum(1 for kw in keywords if kw in text)
                if score > best_score:
                    best_score   = score
                    best_cluster = cluster_name
            if best_cluster and best_score >= 1:
                clusters[best_cluster].append(signal)
            else:
                clusters['uncategorised'].append(signal)
        # Remove tiny clusters
        return {k: v for k, v in clusters.items() if len(v) >= 2}

    def _generate_scenario(self, topic: str, signals: list) -> dict | None:
        """Call LLM to generate a forward-looking scenario from clustered signals."""
        from agents import llm_gateway
        if not llm_gateway.can_spend(self.name):
            return None

        # Check for historical pattern match
        historical_match = self._find_historical_match(signals)

        # Build condensed prompt — ~120 tokens vs the old 300+
        signal_summaries = []
        for s in signals[:5]:
            body   = (s.get('body') or s.get('headline') or '')[:100]
            agent  = s.get('citizen', 'Unknown')
            sil    = s.get('sil_score', '?')
            signal_summaries.append(f'[{agent} | SIL:{sil}] {body}')

        signals_text  = '\n'.join(signal_summaries)
        hist_text     = f'\nHistorical match: {historical_match["precedent"]} ({historical_match["name"]})' if historical_match else ''
        topic_display = topic.replace('_', ' ').title()

        system_prompt = (
            f"You are CASSANDRA, The Scenario Analyst of The Signal Society. "
            f"You synthesise multi-agent intelligence signals into forward-looking scenarios. "
            f"Voice: Precise, analytical, historically-grounded. Never vague. "
            f"Tagline: '{self.tagline}'"
        )

        user_prompt = (
            f"TOPIC CLUSTER: {topic_display}\n"
            f"SIGNALS ({len(signals)} total, showing top 5):\n{signals_text}\n"
            f"{hist_text}\n\n"
            f"Generate ONE scenario dispatch (80-180 words):\n"
            f"- Name the pattern explicitly (pre-announcement, divergence, burial, etc.)\n"
            f"- State what should happen next if pattern holds\n"
            f"- Give a specific timeline (days/weeks/months)\n"
            f"- Confidence: LOW/MEDIUM/HIGH based on signal quality\n"
            f"- Do NOT speculate without citing specific signals above\n\n"
            f"Return ONLY valid JSON:\n"
            '{{"body":"...","headline":"...","tags":["#tag1","#tag2"],"confidence":"MEDIUM","timeline":"..."}}'
        )

        raw = llm_gateway.call(
            agent        = self.name,
            system_prompt= system_prompt,
            user_prompt  = user_prompt,
            max_tokens   = 400,
            temperature  = 0.55,
        )
        if not raw:
            return None

        import json
        text = raw.replace('```json', '').replace('```', '').strip()
        parsed = {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            s = text.find('{')
            e = text.rfind('}') + 1
            if s >= 0 and e > s:
                try:
                    parsed = json.loads(text[s:e])
                except Exception:
                    pass

        body = parsed.get('body', '').strip()
        if not body or len(body) < 40:
            return None

        # Add historical match to body if found
        if historical_match and historical_match['precedent'] not in body:
            body += f" Historical precedent: {historical_match['precedent']}."

        tags = parsed.get('tags', [f'#{topic}', '#scenario', '#CASSANDRA'])
        return {
            'id':         str(uuid.uuid4()),
            'type':       'post',
            'citizen':    self.name,
            'timestamp':  datetime.utcnow().isoformat(),
            'body':       body,
            'headline':   parsed.get('headline', f'Scenario: {topic_display}'),
            'tags':       tags,
            'mentions':   [],
            'reactions':  {'agree': 0, 'flag': 0, 'save': 0},
            'metadata': {
                'scenario_type':     topic,
                'signal_count':      len(signals),
                'confidence':        parsed.get('confidence', 'MEDIUM'),
                'timeline':          parsed.get('timeline', ''),
                'historical_match':  historical_match['name'] if historical_match else None,
                'contributing_agents': list({s.get('citizen', '') for s in signals if s.get('citizen')}),
            },
        }

    def _find_historical_match(self, signals: list) -> dict | None:
        """
        Match current signals to historical patterns.
        Requires 3+ keyword hits (not just 1) to avoid false positives.
        """
        text = ' '.join(
            (s.get('body') or s.get('headline') or '') + ' ' +
            ' '.join(s.get('tags') or [])
            for s in signals
        ).lower()

        best_match = None
        best_score = 0

        for template in self.SCENARIO_TEMPLATES:
            score = sum(1 for kw in template['keywords'] if kw in text)
            # Require 3+ keyword matches AND multiple signals contributing
            contributing = sum(
                1 for s in signals
                if any(kw in (s.get('body','') + ' ' + s.get('headline','')).lower()
                       for kw in template['keywords'])
            )
            if score >= 3 and contributing >= 2 and score > best_score:
                best_score = score
                best_match = template

        return best_match
