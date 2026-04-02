"""Grid Tactics TCG - Web Dashboard

Flask app serving training stats, game replays, and card analytics.
Run with: .venv/Scripts/python.exe dashboard.py
Open: http://localhost:5000
"""

import json
import os
import sys
from pathlib import Path

from flask import Flask, render_template_string, jsonify

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from grid_tactics.db.reader import GameResultReader
from grid_tactics.card_library import CardLibrary

app = Flask(__name__)

DB_PATH = Path("data/training.db")
CARDS_PATH = Path("data/cards")

def get_reader():
    if not DB_PATH.exists():
        return None
    return GameResultReader(DB_PATH)

def get_library():
    if not CARDS_PATH.exists():
        return None
    return CardLibrary.from_directory(CARDS_PATH)

# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grid Tactics TCG - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-bottom: 2px solid #0f3460;
            padding: 20px 40px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header h1 {
            font-size: 24px;
            color: #00d4ff;
            letter-spacing: 1px;
        }
        .header .subtitle {
            color: #888;
            font-size: 14px;
        }
        .nav {
            display: flex;
            gap: 20px;
        }
        .nav a {
            color: #aaa;
            text-decoration: none;
            padding: 8px 16px;
            border-radius: 6px;
            transition: all 0.2s;
            font-size: 14px;
        }
        .nav a:hover, .nav a.active {
            color: #00d4ff;
            background: rgba(0, 212, 255, 0.1);
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 40px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 24px;
            transition: border-color 0.2s;
        }
        .card:hover { border-color: #0f3460; }
        .card h3 {
            color: #00d4ff;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }
        .stat-big {
            font-size: 48px;
            font-weight: 700;
            color: #fff;
            line-height: 1;
        }
        .stat-label {
            font-size: 13px;
            color: #888;
            margin-top: 4px;
        }
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #2a2a4a;
        }
        .stat-row:last-child { border-bottom: none; }
        .stat-row .label { color: #aaa; }
        .stat-row .value { color: #fff; font-weight: 600; }
        .green { color: #4caf50 !important; }
        .red { color: #f44336 !important; }
        .yellow { color: #ff9800 !important; }
        .cyan { color: #00d4ff !important; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 16px;
        }
        th {
            text-align: left;
            padding: 10px 12px;
            color: #00d4ff;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            border-bottom: 2px solid #2a2a4a;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #1a1a2e;
            font-size: 14px;
        }
        tr:hover td { background: rgba(0, 212, 255, 0.05); }
        .bar-container {
            background: #2a2a4a;
            border-radius: 4px;
            height: 8px;
            width: 100%;
            overflow: hidden;
        }
        .bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
        }
        .bar-green { background: linear-gradient(90deg, #4caf50, #66bb6a); }
        .bar-red { background: linear-gradient(90deg, #f44336, #ef5350); }
        .bar-cyan { background: linear-gradient(90deg, #00b4d8, #00d4ff); }
        .chart-container {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
        }
        .chart-container h3 {
            color: #00d4ff;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 16px;
        }
        .win-rate-chart {
            display: flex;
            align-items: flex-end;
            gap: 4px;
            height: 200px;
            padding-top: 20px;
        }
        .chart-bar {
            flex: 1;
            min-width: 20px;
            border-radius: 4px 4px 0 0;
            position: relative;
            transition: height 0.3s;
            cursor: pointer;
        }
        .chart-bar:hover { opacity: 0.8; }
        .chart-bar .tooltip {
            display: none;
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            background: #333;
            color: #fff;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            white-space: nowrap;
            margin-bottom: 4px;
        }
        .chart-bar:hover .tooltip { display: block; }
        .no-data {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
        .no-data h2 { color: #444; margin-bottom: 12px; }
        .no-data p { margin-bottom: 8px; }
        .no-data code {
            background: #1a1a2e;
            padding: 4px 10px;
            border-radius: 4px;
            color: #00d4ff;
        }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-win { background: rgba(76, 175, 80, 0.2); color: #4caf50; }
        .badge-loss { background: rgba(244, 67, 54, 0.2); color: #f44336; }
        .badge-draw { background: rgba(255, 152, 0, 0.2); color: #ff9800; }
        .refresh-note {
            text-align: center;
            color: #555;
            font-size: 12px;
            margin-top: 20px;
        }
        /* Card detail panel */
        .card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 16px;
        }
        .card-tile {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 0;
            cursor: pointer;
            transition: all 0.2s;
            overflow: hidden;
        }
        .card-tile:hover { border-color: #0f3460; transform: translateY(-2px); }
        .card-tile.expanded { border-color: #00d4ff; }
        .card-tile-header {
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .card-tile-name {
            font-size: 16px;
            font-weight: 700;
            color: #fff;
        }
        .card-tile-cost {
            background: #0f3460;
            color: #00d4ff;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
        }
        .card-tile-tags {
            padding: 0 20px 12px;
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        .card-tag {
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }
        .tag-minion { background: rgba(76,175,80,0.15); color: #4caf50; }
        .tag-magic { background: rgba(156,39,176,0.15); color: #ce93d8; }
        .tag-react { background: rgba(255,152,0,0.15); color: #ff9800; }
        .tag-fire { background: rgba(244,67,54,0.15); color: #f44336; }
        .tag-dark { background: rgba(156,39,176,0.15); color: #ce93d8; }
        .tag-light { background: rgba(255,193,7,0.15); color: #ffc107; }
        .tag-neutral { background: rgba(136,136,136,0.15); color: #aaa; }
        .card-tile-stats {
            padding: 0 20px 12px;
            display: flex;
            gap: 16px;
        }
        .card-mini-stat {
            text-align: center;
        }
        .card-mini-stat .val {
            font-size: 20px;
            font-weight: 700;
            color: #fff;
        }
        .card-mini-stat .lbl {
            font-size: 10px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .card-detail {
            display: none;
            padding: 0 20px 20px;
            border-top: 1px solid #2a2a4a;
        }
        .card-tile.expanded .card-detail { display: block; }
        .card-detail h4 {
            color: #00d4ff;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 12px 0 8px;
        }
        .effect-row {
            background: #12121f;
            border: 1px solid #2a2a4a;
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .effect-type { color: #f44336; font-weight: 600; }
        .effect-trigger { color: #ff9800; font-size: 12px; }
        .effect-target { color: #00d4ff; font-size: 12px; }
        .effect-amount {
            font-size: 18px;
            font-weight: 700;
            color: #fff;
        }
        .react-section {
            background: rgba(255,152,0,0.08);
            border: 1px solid rgba(255,152,0,0.2);
            border-radius: 8px;
            padding: 12px 14px;
            margin-top: 8px;
        }
        .react-section .label { color: #ff9800; font-size: 12px; font-weight: 600; }
        .card-id-text { color: #555; font-size: 11px; font-family: monospace; margin-top: 8px; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>GRID TACTICS TCG</h1>
            <div class="subtitle">RL Training Dashboard</div>
        </div>
        <div class="nav">
            <a href="/" class="active">Overview</a>
            <a href="/cards">Cards</a>
            <a href="/api/runs">API</a>
        </div>
    </div>

    <div class="container" id="app">
        <!-- Loaded via JS -->
    </div>

    <script>
    async function loadDashboard() {
        const app = document.getElementById('app');

        // Fetch data
        let runs, cards;
        try {
            const runsResp = await fetch('/api/runs');
            runs = await runsResp.json();
        } catch(e) {
            runs = [];
        }

        if (runs.length === 0) {
            app.innerHTML = `
                <div class="no-data">
                    <h2>No Training Data Yet</h2>
                    <p>Run training first to see stats here:</p>
                    <p><code>train.bat</code> (quick ~5 min) or <code>train_long.bat</code> (full ~30 min)</p>
                    <p style="margin-top:20px;color:#555">This page auto-refreshes every 30 seconds during training.</p>
                </div>
            `;
            setTimeout(loadDashboard, 30000);
            return;
        }

        // Get latest run details
        const latestRun = runs[0];
        const runId = latestRun.run_id;

        let stats, winHistory, games;
        try {
            const [statsR, histR, gamesR] = await Promise.all([
                fetch('/api/runs/' + runId + '/stats'),
                fetch('/api/runs/' + runId + '/win_rate'),
                fetch('/api/runs/' + runId + '/games?limit=50'),
            ]);
            stats = await statsR.json();
            winHistory = await histR.json();
            games = await gamesR.json();
        } catch(e) {
            stats = {total_games:0, win_rate:0, avg_game_length:0};
            winHistory = [];
            games = [];
        }

        const winPct = ((stats.win_rate || 0) * 100).toFixed(1);
        const totalGames = stats.total_games || 0;
        const avgLen = Math.round(stats.avg_game_length || 0);

        // Count wins/losses/draws
        let wins=0, losses=0, draws=0;
        games.forEach(g => {
            if (g.winner === g.training_player) wins++;
            else if (g.winner === null) draws++;
            else losses++;
        });

        // Build win rate chart
        let chartBars = '';
        if (winHistory.length > 0) {
            winHistory.forEach((s, i) => {
                const wr = ((s.win_rate_100 || 0) * 100);
                const h = Math.max(4, wr * 2);
                const color = wr >= 60 ? '#4caf50' : wr >= 40 ? '#ff9800' : '#f44336';
                chartBars += '<div class="chart-bar" style="height:' + h + 'px;background:' + color + '">' +
                    '<span class="tooltip">Step ' + (s.timestep||0) + ': ' + wr.toFixed(1) + '%</span></div>';
            });
        }

        // Recent games table
        let gamesRows = '';
        games.slice(-20).reverse().forEach(g => {
            const result = g.winner === g.training_player ? '<span class="badge badge-win">WIN</span>' :
                          g.winner === null ? '<span class="badge badge-draw">DRAW</span>' :
                          '<span class="badge badge-loss">LOSS</span>';
            gamesRows += '<tr><td>#' + g.episode_num + '</td><td>' + result + '</td>' +
                '<td>' + (g.turn_count||0) + '</td>' +
                '<td>' + (g.p1_final_hp||0) + '</td><td>' + (g.p2_final_hp||0) + '</td></tr>';
        });

        app.innerHTML = `
            <div class="grid">
                <div class="card">
                    <h3>Win Rate</h3>
                    <div class="stat-big ${winPct >= 60 ? 'green' : winPct >= 40 ? 'yellow' : 'red'}">${winPct}%</div>
                    <div class="stat-label">vs Random Opponent</div>
                </div>
                <div class="card">
                    <h3>Games Played</h3>
                    <div class="stat-big cyan">${totalGames}</div>
                    <div class="stat-label">Total training episodes</div>
                </div>
                <div class="card">
                    <h3>Avg Game Length</h3>
                    <div class="stat-big">${avgLen}</div>
                    <div class="stat-label">Turns per game</div>
                </div>
                <div class="card">
                    <h3>Results Breakdown</h3>
                    <div class="stat-row">
                        <span class="label">Wins</span>
                        <span class="value green">${wins}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Losses</span>
                        <span class="value red">${losses}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Draws</span>
                        <span class="value yellow">${draws}</span>
                    </div>
                    <div style="margin-top:12px">
                        <div class="bar-container">
                            <div class="bar-fill bar-green" style="width:${totalGames?wins/totalGames*100:0}%"></div>
                        </div>
                    </div>
                </div>
            </div>

            ${chartBars ? `
            <div class="chart-container">
                <h3>Win Rate Over Training</h3>
                <div class="win-rate-chart">${chartBars}</div>
            </div>` : ''}

            <div class="grid" style="grid-template-columns: 1fr;">
                <div class="card">
                    <h3>Training Run: ${runId}</h3>
                    <div class="stat-row">
                        <span class="label">Started</span>
                        <span class="value">${latestRun.started_at || 'N/A'}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Ended</span>
                        <span class="value">${latestRun.ended_at || 'In progress...'}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Total Timesteps</span>
                        <span class="value">${latestRun.total_timesteps || 'N/A'}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Model</span>
                        <span class="value">${latestRun.model_path || 'Training...'}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Description</span>
                        <span class="value">${latestRun.description || '-'}</span>
                    </div>
                </div>
            </div>

            ${gamesRows ? `
            <div class="card">
                <h3>Recent Games</h3>
                <table>
                    <tr><th>Episode</th><th>Result</th><th>Turns</th><th>P1 HP</th><th>P2 HP</th></tr>
                    ${gamesRows}
                </table>
            </div>` : ''}

            <div class="refresh-note">Auto-refreshes every 30 seconds during training</div>
        `;

        // Auto-refresh
        setTimeout(loadDashboard, 30000);
    }

    // Cards page
    if (window.location.pathname === '/cards') {
        loadCards();
    } else {
        loadDashboard();
    }

    async function loadCards() {
        const app = document.getElementById('app');
        const resp = await fetch('/api/cards');
        const cards = await resp.json();

        const typeTag = { MINION: 'tag-minion', MAGIC: 'tag-magic', REACT: 'tag-react' };
        const attrTag = { FIRE: 'tag-fire', DARK: 'tag-dark', LIGHT: 'tag-light', NEUTRAL: 'tag-neutral' };

        const effectTypeLabels = {
            DAMAGE: 'Damage', HEAL: 'Heal', BUFF_ATTACK: 'Buff ATK', BUFF_HEALTH: 'Buff HP'
        };
        const triggerLabels = {
            ON_PLAY: 'On Play', ON_DEATH: 'On Death', ON_ATTACK: 'On Attack', ON_DAMAGED: 'On Damaged'
        };
        const targetLabels = {
            SINGLE_TARGET: 'Single Target', ALL_ENEMIES: 'All Enemies',
            ADJACENT: 'Adjacent', SELF_OWNER: 'Self/Owner'
        };
        const rangeLabel = (r) => r === 0 ? 'Melee' : r === null || r === undefined ? '-' : 'Range ' + r;

        let tiles = '';
        cards.forEach((c, i) => {
            // Stats row (only for minions)
            let statsHtml = '';
            if (c.card_type === 'MINION') {
                statsHtml = `<div class="card-tile-stats">
                    <div class="card-mini-stat"><div class="val" style="color:#f44336">${c.attack||0}</div><div class="lbl">ATK</div></div>
                    <div class="card-mini-stat"><div class="val" style="color:#4caf50">${c.health||0}</div><div class="lbl">HP</div></div>
                    <div class="card-mini-stat"><div class="val" style="color:#00d4ff">${rangeLabel(c.attack_range)}</div><div class="lbl">Range</div></div>
                </div>`;
            }

            // Effects
            let effectsHtml = '';
            if (c.effects && c.effects.length > 0) {
                effectsHtml = '<h4>Effects</h4>';
                c.effects.forEach(e => {
                    effectsHtml += `<div class="effect-row">
                        <div>
                            <span class="effect-type">${effectTypeLabels[e.type] || e.type}</span>
                            <span class="effect-trigger">${triggerLabels[e.trigger] || e.trigger}</span>
                            <span class="effect-target">${targetLabels[e.target] || e.target}</span>
                        </div>
                        <div class="effect-amount">${e.amount}</div>
                    </div>`;
                });
            } else {
                effectsHtml = '<h4>Effects</h4><div style="color:#555;font-size:13px">No effects (vanilla card)</div>';
            }

            // React effect (multi-purpose)
            let reactHtml = '';
            if (c.is_multi_purpose && c.react_mana_cost !== null) {
                const reactEffect = c.effects.find(e => true); // show react cost
                reactHtml = `<div class="react-section">
                    <div class="label">React Mode (from hand)</div>
                    <div style="margin-top:4px;color:#e0e0e0">
                        Cost: <strong style="color:#00d4ff">${c.react_mana_cost} Mana</strong> |
                        Can be played as a React card instead of deploying as a minion.
                        The card is consumed either way.
                    </div>
                </div>`;
            }

            // Tribe
            let tribeHtml = '';
            if (c.tribe) {
                tribeHtml = `<h4>Tribe</h4><div style="color:#e0e0e0;font-size:14px">${c.tribe}</div>`;
            }

            tiles += `
            <div class="card-tile" onclick="this.classList.toggle('expanded')" id="card-${i}">
                <div class="card-tile-header">
                    <span class="card-tile-name">${c.name}</span>
                    <span class="card-tile-cost">${c.mana_cost}</span>
                </div>
                <div class="card-tile-tags">
                    <span class="card-tag ${typeTag[c.card_type] || ''}">${c.card_type}</span>
                    ${c.attribute ? '<span class="card-tag ' + (attrTag[c.attribute]||'') + '">' + c.attribute + '</span>' : ''}
                    ${c.is_multi_purpose ? '<span class="card-tag tag-react">MULTI-PURPOSE</span>' : ''}
                </div>
                ${statsHtml}
                <div class="card-detail">
                    ${effectsHtml}
                    ${reactHtml}
                    ${tribeHtml}
                    <div class="card-id-text">ID: ${c.card_id}</div>
                </div>
            </div>`;
        });

        // Group by type
        const minions = cards.filter(c => c.card_type === 'MINION').length;
        const magic = cards.filter(c => c.card_type === 'MAGIC').length;
        const react = cards.filter(c => c.card_type === 'REACT').length;

        app.innerHTML = `
            <div class="grid" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 24px;">
                <div class="card" style="text-align:center">
                    <h3>Minions</h3>
                    <div class="stat-big green">${minions}</div>
                </div>
                <div class="card" style="text-align:center">
                    <h3>Magic</h3>
                    <div class="stat-big" style="color:#ce93d8">${magic}</div>
                </div>
                <div class="card" style="text-align:center">
                    <h3>React</h3>
                    <div class="stat-big yellow">${react}</div>
                </div>
            </div>
            <div style="color:#888;font-size:13px;margin-bottom:16px">Click any card to see full details</div>
            <div class="card-grid">
                ${tiles}
            </div>
        `;
    }
    </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route('/')
@app.route('/cards')
def index():
    return render_template_string(TEMPLATE)

@app.route('/api/runs')
def api_runs():
    reader = get_reader()
    if not reader:
        return jsonify([])
    return jsonify(reader.get_runs())

@app.route('/api/runs/<run_id>')
def api_run(run_id):
    reader = get_reader()
    if not reader:
        return jsonify({})
    return jsonify(reader.get_run(run_id))

@app.route('/api/runs/<run_id>/stats')
def api_run_stats(run_id):
    reader = get_reader()
    if not reader:
        return jsonify({})
    return jsonify(reader.get_overall_stats(run_id))

@app.route('/api/runs/<run_id>/win_rate')
def api_win_rate(run_id):
    reader = get_reader()
    if not reader:
        return jsonify([])
    return jsonify(reader.get_win_rate_over_time(run_id))

@app.route('/api/runs/<run_id>/games')
def api_games(run_id):
    from flask import request
    limit = int(request.args.get('limit', 100))
    reader = get_reader()
    if not reader:
        return jsonify([])
    return jsonify(reader.get_game_results(run_id, limit=limit))

@app.route('/api/runs/<run_id>/card_usage')
def api_card_usage(run_id):
    reader = get_reader()
    if not reader:
        return jsonify([])
    return jsonify(reader.get_card_usage(run_id))

@app.route('/api/cards')
def api_cards():
    library = get_library()
    if not library:
        return jsonify([])
    cards = []
    for card_def in library.all_cards:
        cards.append({
            'card_id': card_def.card_id,
            'name': card_def.name,
            'card_type': card_def.card_type.name,
            'attribute': card_def.attribute.name if card_def.attribute else None,
            'tribe': card_def.tribe,
            'mana_cost': card_def.mana_cost,
            'attack': card_def.attack,
            'health': card_def.health,
            'attack_range': card_def.attack_range,
            'is_multi_purpose': card_def.is_multi_purpose,
            'effects': [
                {
                    'type': e.effect_type.name,
                    'trigger': e.trigger.name,
                    'target': e.target.name,
                    'amount': e.amount,
                }
                for e in card_def.effects
            ],
            'react_mana_cost': card_def.react_mana_cost,
        })
    return jsonify(cards)

if __name__ == '__main__':
    print("=" * 50)
    print("  Grid Tactics TCG - Dashboard")
    print("  Open: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
