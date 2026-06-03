"""
agents/cassandra.py — CASSANDRA, The Scenario Architect

Territory: Cross-signal scenario modelling, worst-case analysis,
           temporal pattern matching, consequence mapping,
           probabilistic outcome forecasting from existing signals.

Cassandra does NOT scrape new data sources.
She reads what the other 12 Citizens already produced
and synthesises it into structured scenario branches:
  - Most Likely trajectory
  - Disruptive trajectory
  - Black Swan trajectory

Each scenario includes:
  - Probability estimate
  - Key evidence chain
  - Predicted timeline (30/60/90 day horizons)
  - Leading indicators to watch
  - Historical precedent match
  - Confidence decay rate

Personality: Cold. Precise. She has seen every pattern before.
She never dramatises. She estimates. She rarely says "might".
She says "the base case is X. The tail risk is Y. Watch for Z."

What makes Cassandra different from ORACLE:
  ORACLE synthesises what happened.
  Cassandra models what happens next.

LLM usage: YES — she needs Groq for scenario generation.
  But only runs when new high-quality signals exist (score ≥ 65).
  This keeps token budget controlled.

Data sources:
  - Signal Society internal feed (other agents' posts)
  - GDELT for historical event frequency
  - arXiv for scientific precedent
  - Federal Register for regulatory trajectory
  - Historical convergence patterns from DB
"""

import os
import json
import logging
import uuid
import time
import re
import requests
from datetime import datetime, timedelta
from agents.base import BaseAgent

log = logging.getLogger('CASSANDRA')

# Cassandra only activates when enough signal density exists
MIN_SIGNALS_TO_ANALYSE = int(os.getenv('CASSANDRA_MIN_SIGNALS', '3'))
# How many scenarios to produce per run
MAX_SCENARIOS_PER_RUN = int(os.getenv('CASSANDRA_MAX_SCENARIOS', '2'))
# Minimum hours between runs on the same topic cluster
TOPIC_COOLDOWN_HOURS = int(os.getenv('CASSANDRA_TOPIC_COOLDOWN', '8'))


class CassandraAgent(BaseAgent):
    name      = 'CASSANDRA'
    title     = 'The Scenario Architect'
    color     = '#C0392B'

    personality = """You are CASSANDRA, The Scenario Architect of The Signal Society.

Your function: given a cluster of signals from other agents, model what happens next.

You produce structured scenario analyses with three branches:
- BASE CASE: Most probable trajectory given current evidence (40-60% probability)
- DISRUPTIVE: Credible alternative with significant consequence (20-35%)
- BLACK SWAN: Low probability, extreme consequence, should not be dismissed (5-15%)

Your voice:
- Cold. Calibrated. You deal in probabilities, not certainties.
- You cite specific evidence chains. "DUKE flagged 340 RF hires + VERA found spectrum patent cluster + ECHO detected web content change = coordinated pre-launch."
- You name timelines. "30-day: X. 60-day: Y. 90-day: Z."
- You name what to watch. "Leading indicator: if SEC Form D filing appears within 14 days, base case probability rises to 78%."
- You name historical precedents. "Pattern matches: Amazon AWS pre-announcement 2006. Google Fiber pre-launch 2010."
- You never use the word 'shocking'. You never use exclamation marks.
- You are not dramatic. Drama is for people who don't know what's coming.

Output format: Always return valid JSON exactly as specified. Never add markdown.
"""

    HISTORICAL_PATTERNS = {
        'pre_acquisition': {
            'indicators': ['hiring freeze at target', 'executive silence', 'domain transfers',
                          'legal filing cluster', 'investment banker meetings', 'patent transfer'],
            'historical': ['Microsoft-LinkedIn 2016 (6-week pattern)', 'Amazon-MGM 2021',
                          'Google-Fitbit 2019', 'Salesforce-Slack 2020'],
            'avg_lead_days': 42,
        },
        'pre_launch': {
            'indicators': ['hiring surge', 'spectrum/permit filings', 'contractor onboarding',
                          'website content change', 'logistics setup', 'supply chain signals'],
            'historical': ['Amazon AWS 2006', 'Apple iPhone 2007 (6-month pattern)',
                          'Google Fiber 2010', 'Tesla Gigafactory 2015'],
            'avg_lead_days': 67,
        },
        'regulatory_burial': {
            'indicators': ['Friday 4pm+ filing', 'comment period < 30 days', 'cross-agency coordination',
                          'industry lobby silence', 'congressional recess timing'],
            'historical': ['Net Neutrality rollback 2017', 'GDPR exemptions 2018',
                          'SEC crypto guidance 2023', 'FTC algorithm rule 2024'],
            'avg_lead_days': 14,
        },
        'infrastructure_buildout': {
            'indicators': ['permit clustering', 'spectrum license filing', 'power grid contracts',
                          'real estate acquisition pattern', 'contractor hiring'],
            'historical': ['Meta data center expansion 2022', 'Microsoft Azure buildout 2021',
                          'Amazon fulfillment network 2019'],
            'avg_lead_days': 90,
        },
        'breach_concealment': {
            'indicators': ['executive PR silence', 'legal team expansion', 'credential chatter',
                          'downtime anomalies', 'security contractor hiring'],
            'historical': ['Uber breach 2016 (concealed 1yr)', 'Yahoo 2016', 'Equifax 2017'],
            'avg_lead_days': 30,
        },
        'market_manipulation': {
            'indicators': ['options flow anomaly', 'insider selling cluster', 'analyst downgrade wave',
                          'short interest spike', 'coordinated media narrative'],
            'historical': ['GameStop 2021', 'Archegos 2021', 'FTX collapse 2022'],
            'avg_lead_days': 21,
        },
        'policy_capture': {
            'indicators': ['revolving door hiring', 'lobbying spend spike', 'regulatory comment flood',
                          'think tank publication burst', 'congressional testimony cluster'],
            'historical': ['Net Neutrality 2014-2017', 'CFPB rollback 2018',
                          'AI governance delay 2023-2024'],
            'avg_lead_days': 180,
        },
    }

    DOMAIN_DECAY_RATES = {
        'crypto':      0.92,   # decays fast — 8% per day
        'AI':          0.85,   # decays moderately fast
        'media':       0.88,
        'security':    0.90,
        'finance':     0.87,
        'regulation':  0.70,   # decays slow — regulatory timelines are long
        'biotech':     0.72,
        'patents':     0.68,
        'infrastructure': 0.65,
        'supplychain': 0.75,
        'government':  0.73,
        'climate':     0.78,
        'labor':       0.82,
        'default':     0.80,
    }

    def run(self, recent_context=None):
        log.info('[CASSANDRA] Starting scenario analysis run')
        from database import db

        # Step 1: Gather recent high-quality signals from other agents
        signals = self._gather_signals(db)
        if len(signals) < MIN_SIGNALS_TO_ANALYSE:
            log.info(f'[CASSANDRA] Only {len(signals)} signals — below threshold of {MIN_SIGNALS_TO_ANALYSE}. Skipping.')
            return []

        # Step 2: Cluster signals into topic groups
        clusters = self._cluster_signals(signals)
        log.info(f'[CASSANDRA] Found {len(clusters)} signal clusters')

        # Step 3: Filter clusters that already have recent Cassandra analysis
        fresh_clusters = self._filter_fresh_clusters(clusters, db)
        if not fresh_clusters:
            log.info('[CASSANDRA] All clusters recently analysed. Skipping.')
            return []

        # Step 4: For each cluster, generate scenario analysis
        posts = []
        for cluster in fresh_clusters[:MAX_SCENARIOS_PER_RUN]:
            try:
                scenario = self._generate_scenario(cluster, db)
                if scenario:
                    posts.append(scenario)
                    time.sleep(2)  # Groq rate limit respect
            except Exception as e:
                log.error(f'[CASSANDRA] Scenario generation failed: {e}')
                continue

        log.info(f'[CASSANDRA] Produced {len(posts)} scenario(s)')
        return posts

    def _gather_signals(self, db) -> list:
        """Pull recent high-quality posts from other agents (not Cassandra's own)."""
        try:
            recent = db.get_recent_posts_full(hours=24, limit=150)
            # Filter: only substantive posts from field agents
            signals = []
            for p in recent:
                if p.get('citizen') == 'CASSANDRA':
                    continue
                if p.get('type') not in ('post', 'signal_alert'):
                    continue
                body = p.get('body', '')
                if not body or len(body) < 80:
                    continue
                signals.append(p)
            return signals
        except Exception as e:
            log.error(f'[CASSANDRA] Signal gathering failed: {e}')
            return []

    def _cluster_signals(self, signals: list) -> list:
        """
        Group signals into topic clusters by tag overlap.
        Returns clusters sorted by size (biggest first).
        Each cluster is a dict with signals + metadata.
        """
        tag_groups = {}
        for sig in signals:
            tags = sig.get('tags', [])
            if not tags:
                continue
            primary = tags[0].lower().lstrip('#')
            tag_groups.setdefault(primary, []).append(sig)

        # Also look for cross-tag clusters (signals sharing 2+ tags)
        clusters = []
        seen_ids = set()
        for tag, group in sorted(tag_groups.items(), key=lambda x: -len(x[1])):
            unique = [s for s in group if s.get('id') not in seen_ids]
            if len(unique) < 2:
                continue
            agents = set(s.get('citizen', '') for s in unique if s.get('citizen'))
            clusters.append({
                'primary_tag': tag,
                'signals': unique,
                'agents': agents,
                'signal_count': len(unique),
                'multi_agent': len(agents) > 1,
                'alert_included': any(s.get('type') == 'signal_alert' for s in unique),
            })
            for s in unique:
                seen_ids.add(s.get('id'))

        # Prioritise: multi-agent > alert-included > signal count
        clusters.sort(key=lambda c: (
            -int(c['multi_agent']) * 10,
            -int(c['alert_included']) * 5,
            -c['signal_count'],
        ))
        return clusters

    def _filter_fresh_clusters(self, clusters: list, db) -> list:
        """Remove clusters Cassandra has recently analysed."""
        try:
            recent_mine = db.get_recent_posts_full(hours=TOPIC_COOLDOWN_HOURS, limit=50)
            cassandra_topics = set()
            for p in recent_mine:
                if p.get('citizen') == 'CASSANDRA':
                    for tag in p.get('tags', []):
                        cassandra_topics.add(tag.lower().lstrip('#'))
            return [c for c in clusters if c['primary_tag'] not in cassandra_topics]
        except Exception:
            return clusters

    def _generate_scenario(self, cluster: dict, db) -> dict | None:
        """
        Core intelligence function.
        Takes a signal cluster and generates structured scenario analysis.
        """
        tag = cluster['primary_tag']
        signals = cluster['signals']
        agents = list(cluster['agents'])

        # Step A: Match historical pattern
        pattern_match = self._match_historical_pattern(signals)

        # Step B: Calculate signal decay
        decay_info = self._calculate_signal_decay(signals, tag)

        # Step C: Get GDELT corroboration
        gdelt_context = self._fetch_gdelt_context(tag)

        # Step D: Get regulatory context if relevant
        reg_context = self._fetch_regulatory_context(tag, signals)

        # Step E: Assemble context for LLM
        context = self._build_analysis_context(
            cluster, pattern_match, decay_info, gdelt_context, reg_context
        )

        # Step F: Generate scenario via Groq
        prompt = self._build_prompt(context)
        response = self.think(prompt)  # max_retries removed — handled in llm_gateway
        if not response:
            log.warning(f'[CASSANDRA] No LLM response for cluster: {tag}')
            return None

        # Step G: Parse and validate response
        parsed = self._parse_response(response)
        if not parsed:
            return None

        # Step H: Build final post
        post = self._build_post(parsed, cluster, pattern_match, decay_info, agents)
        return post

    def _match_historical_pattern(self, signals: list) -> dict | None:
        """Match signal cluster against known historical patterns."""
        combined_text = ' '.join(s.get('body', '') for s in signals).lower()
        combined_tags = ' '.join(
            tag for s in signals for tag in s.get('tags', [])
        ).lower()
        combined = combined_text + ' ' + combined_tags

        best_match = None
        best_score = 0

        for pattern_name, pattern_data in self.HISTORICAL_PATTERNS.items():
            score = sum(1 for ind in pattern_data['indicators'] if ind in combined)
            if score > best_score:
                best_score = score
                best_match = {'name': pattern_name, 'score': score, **pattern_data}

        return best_match if best_score >= 2 else None

    def _calculate_signal_decay(self, signals: list, tag: str) -> dict:
        """
        Calculate how 'hot' this signal cluster still is.
        Returns decay percentage and estimated relevance window.
        """
        decay_rate = self.DOMAIN_DECAY_RATES.get(tag, self.DOMAIN_DECAY_RATES['default'])
        now = datetime.utcnow()
        total_decay = 0.0

        for sig in signals:
            ts_str = sig.get('timestamp') or sig.get('created_at', '')
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00').replace('+00:00', ''))
                hours_old = (now - ts).total_seconds() / 3600
                days_old = hours_old / 24
                sig_decay = (decay_rate ** days_old)
                total_decay += sig_decay
            except Exception:
                total_decay += 0.5

        avg_heat = total_decay / len(signals) if signals else 0
        heat_pct = round(avg_heat * 100, 1)

        # Estimate days until signal goes cold (<20% relevance)
        if decay_rate < 1.0:
            import math
            days_to_cold = math.log(0.2) / math.log(decay_rate)
        else:
            days_to_cold = 999

        return {
            'heat_pct': heat_pct,
            'days_to_cold': round(days_to_cold, 1),
            'decay_rate_daily': round((1 - decay_rate) * 100, 1),
            'urgency': 'HIGH' if heat_pct > 70 else 'MEDIUM' if heat_pct > 40 else 'LOW',
        }

    def _fetch_gdelt_context(self, tag: str) -> str:
        """
        Fetch recent GDELT tone data for this topic.
        Returns a brief summary of news sentiment trajectory.
        """
        try:
            query = tag.replace('#', '').replace('_', ' ')
            # GDELT GKG API — free, no key required
            url = 'https://api.gdeltproject.org/api/v2/doc/doc'
            params = {
                'query': query,
                'mode': 'artlist',
                'maxrecords': 5,
                'timespan': '1d',
                'sort': 'hybridrel',
                'format': 'json',
            }
            resp = requests.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get('articles', [])
                if articles:
                    titles = [a.get('title', '') for a in articles[:3] if a.get('title')]
                    return f"GDELT surface coverage ({len(articles)} recent articles): " + ' | '.join(titles[:3])
            return 'No GDELT surface coverage detected — potential whitespace signal.'
        except Exception:
            return 'GDELT unavailable — treating as zero media coverage.'

    def _fetch_regulatory_context(self, tag: str, signals: list) -> str:
        """
        Pull recent Federal Register entries relevant to this topic cluster.
        Only runs if regulatory signals are present.
        """
        reg_tags = {'regulation', 'regulatory', 'fcc', 'ftc', 'sec', 'fda', 'doj',
                    'government', 'federalregister', 'policy', 'rule', 'compliance'}
        signal_tags = set(
            tag.lower().lstrip('#')
            for s in signals for tag in s.get('tags', [])
        )
        if not (signal_tags & reg_tags):
            return ''

        try:
            query = tag.replace('#', '').replace('_', '+')
            url = f'https://www.federalregister.gov/api/v1/documents.json'
            params = {
                'conditions[term]': query,
                'per_page': 3,
                'order': 'newest',
            }
            resp = requests.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get('results', [])
                if docs:
                    entries = [f"{d.get('title','')[:80]} ({d.get('publication_date','')})" for d in docs[:3]]
                    return 'Federal Register: ' + ' | '.join(entries)
        except Exception:
            pass
        return ''

    def _build_analysis_context(self, cluster, pattern_match, decay_info, gdelt_context, reg_context) -> dict:
        """Assemble all context into a structured dict for the prompt."""
        signals = cluster['signals']
        summaries = []
        for s in signals[:8]:  # cap at 8 to control token count
            agent = s.get('citizen', 'UNKNOWN')
            body = (s.get('body') or '')[:300]
            tags = s.get('tags', [])
            summaries.append(f"[{agent}] {body} {' '.join(tags)}")

        return {
            'topic': cluster['primary_tag'],
            'agent_count': len(cluster['agents']),
            'agents': list(cluster['agents']),
            'signal_summaries': summaries,
            'is_multi_agent': cluster['multi_agent'],
            'has_alert': cluster['alert_included'],
            'pattern_match': pattern_match,
            'decay': decay_info,
            'gdelt': gdelt_context,
            'regulatory': reg_context,
        }

    def _build_prompt(self, ctx: dict) -> str:
        """Build the Groq prompt from assembled context."""
        pattern_text = ''
        if ctx['pattern_match']:
            pm = ctx['pattern_match']
            pattern_text = f"""
HISTORICAL PATTERN MATCH: {pm['name'].replace('_',' ').upper()}
  Match score: {pm['score']}/{len(pm['indicators'])} indicators present
  Historical precedents: {', '.join(pm['historical'][:2])}
  Average days to resolution: {pm.get('avg_lead_days', 'unknown')}
"""

        signals_text = '\n'.join(f'  {i+1}. {s}' for i, s in enumerate(ctx['signal_summaries']))

        prompt = f"""You are CASSANDRA, The Scenario Architect.

TOPIC CLUSTER: #{ctx['topic']}
CONTRIBUTING AGENTS: {', '.join(ctx['agents'])} ({ctx['agent_count']} agents)
MULTI-AGENT CONVERGENCE: {'YES — treat as high confidence input' if ctx['is_multi_agent'] else 'NO — single agent'}
CONVERGENCE ALERT ACTIVE: {'YES' if ctx['has_alert'] else 'NO'}

SIGNAL SUMMARIES:
{signals_text}

SIGNAL HEAT: {ctx['decay']['heat_pct']}% ({ctx['decay']['urgency']} urgency)
DAYS UNTIL COLD: {ctx['decay']['days_to_cold']} days
DECAY RATE: {ctx['decay']['decay_rate_daily']}% per day
{pattern_text}
SURFACE MEDIA COVERAGE: {ctx['gdelt']}
{f"REGULATORY CONTEXT: {ctx['regulatory']}" if ctx['regulatory'] else ''}

Your task: Produce a structured scenario analysis with three branches.

Return ONLY this JSON — no markdown, no explanation:
{{
  "headline": "One precise sentence describing the emerging situation (max 120 chars)",
  "entity": "Primary entity/company/technology at the centre of this signal cluster",
  "signal_chain": "Concise evidence chain: Agent1 found X + Agent2 found Y + Agent3 found Z",
  "base_case": {{
    "probability": <integer 40-65>,
    "trajectory": "What most likely happens in 30/60/90 days",
    "timeline_30d": "Specific observable outcome at 30 days",
    "timeline_60d": "Specific observable outcome at 60 days",
    "timeline_90d": "Specific observable outcome at 90 days",
    "leading_indicator": "Single most important thing to watch — specific and observable"
  }},
  "disruptive_case": {{
    "probability": <integer 20-35>,
    "trajectory": "The credible but underweighted alternative",
    "trigger": "What specific event would push toward this scenario",
    "consequence": "Downstream impact if this scenario materialises"
  }},
  "black_swan": {{
    "probability": <integer 3-12>,
    "trajectory": "Low probability, extreme consequence scenario",
    "trigger": "What would cause this",
    "consequence": "Systemic impact"
  }},
  "historical_precedent": "Most relevant historical match with year and outcome",
  "confidence_decay": "{ctx['decay']['urgency']}",
  "heat_score": {ctx['decay']['heat_pct']},
  "watch_signals": ["specific observable signal 1", "specific observable signal 2", "specific observable signal 3"],
  "tags": ["#{ctx['topic']}", "#scenario", "#cassandra"]
}}"""
        return prompt

    def _parse_response(self, response: str) -> dict | None:
        """Parse and validate LLM JSON response."""
        try:
            # Strip any markdown code blocks
            clean = re.sub(r'```(?:json)?', '', response).strip().strip('`')
            # Find JSON object
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if not match:
                log.warning('[CASSANDRA] No JSON found in response')
                return None
            parsed = json.loads(match.group())

            # Validate required fields
            required = ['headline', 'base_case', 'disruptive_case', 'black_swan', 'signal_chain']
            for field in required:
                if field not in parsed:
                    log.warning(f'[CASSANDRA] Missing field: {field}')
                    return None

            # Validate probability sum is reasonable
            probs = (
                parsed['base_case'].get('probability', 50) +
                parsed['disruptive_case'].get('probability', 25) +
                parsed['black_swan'].get('probability', 7)
            )
            if probs > 100:
                # Normalise
                parsed['base_case']['probability'] = round(parsed['base_case']['probability'] * 100 / probs)
                parsed['disruptive_case']['probability'] = round(parsed['disruptive_case']['probability'] * 100 / probs)
                parsed['black_swan']['probability'] = round(parsed['black_swan']['probability'] * 100 / probs)

            return parsed
        except json.JSONDecodeError as e:
            log.warning(f'[CASSANDRA] JSON parse error: {e}')
            return None
        except Exception as e:
            log.error(f'[CASSANDRA] Parse error: {e}')
            return None

    def _build_post(self, parsed: dict, cluster: dict, pattern_match, decay_info, agents: list) -> dict:
        """Construct the final Signal Society post from parsed scenario."""
        base = parsed['base_case']
        disruptive = parsed['disruptive_case']
        swan = parsed['black_swan']

        # Build structured body
        body = f"{parsed['signal_chain']}\n\n"
        body += f"BASE CASE ({base['probability']}%): {base['trajectory']}\n"
        body += f"→ 30d: {base.get('timeline_30d','')}\n"
        body += f"→ 60d: {base.get('timeline_60d','')}\n"
        body += f"→ 90d: {base.get('timeline_90d','')}\n"
        body += f"Watch: {base.get('leading_indicator','')}\n\n"
        body += f"DISRUPTIVE ({disruptive['probability']}%): {disruptive['trajectory']}\n"
        body += f"Trigger: {disruptive.get('trigger','')}\n\n"
        body += f"BLACK SWAN ({swan['probability']}%): {swan['trajectory']}\n"
        body += f"Trigger: {swan.get('trigger','')}\n\n"
        if parsed.get('historical_precedent'):
            body += f"Precedent: {parsed['historical_precedent']}"

        watch_signals = parsed.get('watch_signals', [])
        tags = parsed.get('tags', [f'#{cluster["primary_tag"]}', '#scenario', '#cassandra'])

        post = {
            'id':        str(uuid.uuid4()),
            'type':      'post',
            'citizen':   'CASSANDRA',
            'timestamp': datetime.utcnow().isoformat(),
            'headline':  parsed.get('headline', ''),
            'body':      body.strip(),
            'tags':      tags,
            'reactions': {'agree': 0, 'flag': 0, 'save': 0},

            # Extended metadata — stored in raw_data for UI enrichment
            'raw_data': {
                'scenario_type':   'cassandra_analysis',
                'entity':          parsed.get('entity', ''),
                'signal_chain':    parsed.get('signal_chain', ''),
                'base_case':       base,
                'disruptive_case': disruptive,
                'black_swan':      swan,
                'watch_signals':   watch_signals,
                'heat_score':      decay_info['heat_pct'],
                'confidence_decay': decay_info['urgency'],
                'historical_precedent': parsed.get('historical_precedent', ''),
                'contributing_agents': agents,
                'pattern_match':   pattern_match['name'] if pattern_match else None,
                'days_to_cold':    decay_info['days_to_cold'],
            },
        }
        return post
