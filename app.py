
from flask import Flask, jsonify, request
from database import Database
from agents.council import CouncilAgent
from agents.oracle import OracleAgent

app = Flask(__name__)
db = Database()
council = CouncilAgent(db)
oracle = OracleAgent(db)

@app.route('/api/stats/weekly')
def weekly_stats(): return jsonify(db.get_weekly_stats())

@app.route('/api/stats/divergence')
def divergence(): return jsonify(db.get_divergence_map())

@app.route('/api/trigger/council', methods=['POST'])
def trigger_council():
    id = council.run_session()
    return jsonify({"status": "success", "id": id})

@app.route('/api/trigger/oracle', methods=['POST'])
def trigger_oracle():
    oracle.process_council_sessions()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
