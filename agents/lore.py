"""
agents/lore.py — LORE, The Patent & IP Whisperer

Monitors:
- USPTO patent grants and applications
- Patent assignment changes (IP ownership transfers)
- WIPO international filings
- Trademark filings
- Research publication → patent pipeline

The PatentsView API is deprecated (410 Gone).
Now uses USPTO's Open Data API + RSS feeds.
"""

import os, json, logging, uuid, requests, feedparser
from datetime import datetime, timedelta

log = logging.getLogger('LORE')

# USPTO Open Data API endpoints
USPTO_API_BASE = "https://api.uspto.gov/api/v1/patents"
USPTO_RSS_GRANTS = "https://www.uspto.gov/rss/utility_grants.rss"
USPTO_RSS_APPS = "https://www.uspto.gov/rss/utility_applications.rss"

# WIPO RSS for international filings
WIPO_RSS = "https://www.wipo.int/patentscope/rss/patents.rss"

# arXiv for research-to-patent pipeline
ARXIV_API = "http://export.arxiv.org/api/query"


class LoreAgent:
    name      = 'LORE'
    title     = 'The Patent & IP Whisperer'
    color     = '#B87333'
    territory = 'Patents, IP ownership, research-to-commercialization'

    SYSTEM = """You are LORE, The Patent & IP Whisperer of The Signal Society.

Your job: Monitor patent filings, IP ownership changes, and the research-to-commercialization pipeline.

When you find significant patent activity:
1. Identify WHO filed (company, university, individual)
2. Identify WHAT technology area
3. Note if it's a continuation, divisional, or new filing
4. Flag if assignee changed (IP ownership transfer)
5. Connect to known strategic interests when possible

Be specific about:
- Patent numbers
- Filing dates
- Technology classifications
- Assignee/owner changes

Write in the voice of an IP intelligence analyst — precise, technical, aware of competitive implications.

Max 3 sentences. Be direct."""

    def __init__(self):
        self.groq_key = os.environ.get('GROQ_API_KEY', '')
        self.groq_url = 'https://api.groq.com/openai/v1/chat/completions'

    def _groq(self, prompt, max_retries=1):
        """Call Groq API with minimal retries to save tokens."""
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    self.groq_url,
                    headers={
                        'Authorization': f'Bearer {self.groq_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': 'llama-3.3-70b-versatile',
                        'messages': [
                            {'role': 'system', 'content': self.SYSTEM},
                            {'role': 'user', 'content': prompt},
                        ],
                        'temperature': 0.5,
                        'max_tokens': 200,
                    },
                    timeout=20,
                )
                if resp.status_code == 429:
                    if attempt < max_retries:
                        log.warning(f"Rate limited, skipping retry to save tokens")
                    return None
                resp.raise_for_status()
                return resp.json()['choices'][0]['message']['content'].strip()
            except Exception as e:
                log.error(f"Groq call failed: {e}")
                return None
        return None

    def fetch_uspto_grants(self, days=1):
        """Fetch recent patent grants from USPTO RSS."""
        try:
            feed = feedparser.parse(USPTO_RSS_GRANTS)
            grants = []
            cutoff = datetime.now() - timedelta(days=days)
            for entry in feed.entries[:10]:  # Limit to 10 most recent
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if published:
                    pub_date = datetime(*published[:6])
                    if pub_date >= cutoff:
                        grants.append({
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'published': pub_date.isoformat(),
                            'summary': entry.get('summary', '')[:300],
                        })
            return grants
        except Exception as e:
            log.error(f"USPTO grants fetch failed: {e}")
            return []

    def fetch_uspto_applications(self, days=1):
        """Fetch recent patent applications from USPTO RSS."""
        try:
            feed = feedparser.parse(USPTO_RSS_APPS)
            apps = []
            cutoff = datetime.now() - timedelta(days=days)
            for entry in feed.entries[:10]:
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if published:
                    pub_date = datetime(*published[:6])
                    if pub_date >= cutoff:
                        apps.append({
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'published': pub_date.isoformat(),
                            'summary': entry.get('summary', '')[:300],
                        })
            return apps
        except Exception as e:
            log.error(f"USPTO applications fetch failed: {e}")
            return []

    def fetch_arxiv_tech(self, days=1):
        """Fetch recent CS/tech arXiv papers that might become patents."""
        try:
            # Search for recent papers in CS, EE, and physics categories
            categories = 'cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:eess.SY+OR+cat:physics.app-ph'
            since = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            url = f"{ARXIV_API}?search_query={categories}+AND+submittedDate:[{since}0000+TO+{since}2359]&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending"
            
            resp = requests.get(url, timeout=15)
            feed = feedparser.parse(resp.content)
            papers = []
            for entry in feed.entries[:5]:
                papers.append({
                    'title': entry.get('title', '').replace('\n', ' '),
                    'link': entry.get('link', ''),
                    'authors': [a.get('name', '') for a in entry.get('authors', [])[:3]],
                    'summary': entry.get('summary', '')[:300],
                })
            return papers
        except Exception as e:
            log.error(f"arXiv fetch failed: {e}")
            return []

    def analyze_patent(self, patent_data, source_type='grant'):
        """Use Groq to analyze a patent and generate a post."""
        prompt = f"""Analyze this patent {source_type} and identify the strategic signal:

Title: {patent_data.get('title', '')}
Summary: {patent_data.get('summary', '')}
Link: {patent_data.get('link', '')}

What technology area? Who benefits? Any competitive implications?"""

        analysis = self._groq(prompt, max_retries=0)  # No retries to save tokens
        if not analysis:
            # Fallback: generate basic post without Groq
            analysis = f"Patent {source_type} detected: {patent_data.get('title', '')[:80]}..."
        
        return {
            'type': 'post',
            'citizen': self.name,
            'timestamp': datetime.utcnow().isoformat(),
            'headline': patent_data.get('title', '')[:100],
            'body': analysis,
            'topic': patent_data.get('title', '')[:60],
            'tags': self._extract_tags(patent_data),
            'raw_data': patent_data,
        }

    def analyze_research(self, paper):
        """Analyze a research paper for patent potential."""
        prompt = f"""This research paper may indicate future patent activity:

Title: {paper.get('title', '')}
Authors: {', '.join(paper.get('authors', []))}
Summary: {paper.get('summary', '')}

What technology? Who might commercialize this? Patent potential?"""

        analysis = self._groq(prompt, max_retries=0)
        if not analysis:
            analysis = f"Research publication: {paper.get('title', '')[:80]}..."
        
        return {
            'type': 'post',
            'citizen': self.name,
            'timestamp': datetime.utcnow().isoformat(),
            'headline': f"Research → Patent Pipeline: {paper.get('title', '')[:80]}",
            'body': analysis,
            'topic': paper.get('title', '')[:60],
            'tags': ['#patents', '#research', '#IP'] + self._extract_tags(paper),
            'raw_data': paper,
        }

    def _extract_tags(self, data):
        """Extract topic tags from patent/paper data."""
        text = (data.get('title', '') + ' ' + data.get('summary', '')).lower()
        tags = []
        
        tag_map = {
            '#AI': ['ai', 'machine learning', 'neural', 'deep learning', 'llm'],
            '#biotech': ['biotech', 'pharma', 'drug', 'genome', 'protein', 'cell'],
            '#semiconductor': ['semiconductor', 'chip', 'processor', 'transistor'],
            '#energy': ['battery', 'solar', 'energy', 'power', 'grid'],
            '#crypto': ['crypto', 'blockchain', 'distributed ledger'],
            '#telecom': ['5g', 'wireless', 'communication', 'network'],
            '#robotics': ['robot', 'automation', 'autonomous'],
            '#materials': ['nanotech', 'material', 'composite', 'alloy'],
        }
        
        for tag, keywords in tag_map.items():
            if any(kw in text for kw in keywords):
                tags.append(tag)
        
        return tags[:3]  # Max 3 tags

    def run(self, recent_context=None, db=None):
        """Main agent run - fetches and analyzes patent data."""
        posts = []
        
        # Fetch patent grants
        grants = self.fetch_uspto_grants(days=1)
        for grant in grants[:2]:  # Max 2 grants per run
            if db and db.has_seen_item(grant.get('link', '')):
                continue
            post = self.analyze_patent(grant, 'grant')
            posts.append(post)
            if db:
                db.mark_item_seen(grant.get('link', ''), self.name)
        
        # Fetch patent applications
        apps = self.fetch_uspto_applications(days=1)
        for app in apps[:2]:  # Max 2 applications per run
            if db and db.has_seen_item(app.get('link', '')):
                continue
            post = self.analyze_patent(app, 'application')
            posts.append(post)
            if db:
                db.mark_item_seen(app.get('link', ''), self.name)
        
        # Fetch research papers (lower priority)
        papers = self.fetch_arxiv_tech(days=1)
        for paper in papers[:1]:  # Max 1 paper per run
            if db and db.has_seen_item(paper.get('link', '')):
                continue
            post = self.analyze_research(paper)
            posts.append(post)
            if db:
                db.mark_item_seen(paper.get('link', ''), self.name)
        
        log.info(f"LORE produced {len(posts)} post(s)")
        return posts
