
class CouncilAgent:
    def __init__(self, db):
        self.db = db

    def run_session(self, topic="Global Intelligence"):
        debate = {
            "AXIOM": "Pattern detected: Infrastructure shift.",
            "DOUBT": "REX data suggests friction.",
            "LACUNA": "Ignoring quantum protocols."
        }
        combined = "\n".join([f"[{m}]: {c}" for m, c in debate.items()])
        return self.db.save_council_session(topic, combined)
