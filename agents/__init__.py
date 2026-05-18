"""
The Signal Society — Agent Package
13 autonomous intelligence agents + base infrastructure

Agents: VERA, DUKE, MIRA, SOL, NOVA, ECHO, KAEL,
        FLUX, REX, VIGIL, LORE, SPECTER, HERMES, CASSANDRA

New in v2:
  - llm_gateway.py: Central rate limiter, token budget, response cache
  - base.py v2: Pre-LLM gate, structured prompts, cached context
  - All agents: _agent_specific_gate(), MAX_THINK_CALLS_PER_RUN, stable IDs
"""
