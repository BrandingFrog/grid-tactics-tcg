"""Grid Tactics TCG - Web Dashboard

Flask app serving training stats, game replays, card analytics,
and live cloud training monitoring across RunPod GPU pods.

Run with: .venv/Scripts/python.exe dashboard.py
Open: http://localhost:5000        (local training)
      http://localhost:5000/cloud  (cloud GPU monitoring)
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, render_template_string, jsonify, request as flask_request

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from grid_tactics.db.reader import GameResultReader
from grid_tactics.card_library import CardLibrary

app = Flask(__name__)

DB_PATH = Path("data/training.db")
CARDS_PATH = Path("data/cards")
CLOUD_DB_DIR = Path("data/cloud_dbs")
CLOUD_DB_DIR.mkdir(parents=True, exist_ok=True)

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
        .tag-wood { background: rgba(76,175,80,0.15); color: #66bb6a; }
        .tag-fire { background: rgba(244,67,54,0.15); color: #f44336; }
        .tag-earth { background: rgba(141,110,99,0.15); color: #bcaaa4; }
        .tag-water { background: rgba(33,150,243,0.15); color: #42a5f5; }
        .tag-metal { background: rgba(158,158,158,0.15); color: #bdbdbd; }
        .tag-dark { background: rgba(156,39,176,0.15); color: #ce93d8; }
        .tag-light { background: rgba(255,193,7,0.15); color: #ffc107; }
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
            <a href="/" class="active">Local</a>
            <a href="/cloud">Cloud</a>
            <a href="/cards">Cards</a>
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
                const wr = ((s.win_rate || 0) * 100);
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
        const elemTag = { WOOD: 'tag-wood', FIRE: 'tag-fire', EARTH: 'tag-earth', WATER: 'tag-water', METAL: 'tag-metal', DARK: 'tag-dark', LIGHT: 'tag-light' };

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

            // Tutor target
            let tutorHtml = '';
            if (c.tutor_target) {
                tutorHtml = `<div style="color:#42a5f5;font-size:13px;margin-top:4px">On Summon: Add <strong>${c.tutor_target}</strong> from deck to hand</div>`;
            }

            // Summon sacrifice
            let sacHtml = '';
            if (c.discard_cost_tribe) {
                sacHtml = `<div style="color:#ff7043;font-size:13px;margin-top:4px">Summon Cost: Destroy a <strong>${c.discard_cost_tribe}</strong> in hand</div>`;
            }

            tiles += `
            <div class="card-tile" onclick="this.classList.toggle('expanded')" id="card-${i}">
                <div class="card-tile-header">
                    <span class="card-tile-name">${c.name}</span>
                    <span class="card-tile-cost">${c.mana_cost}</span>
                </div>
                <div class="card-tile-tags">
                    <span class="card-tag ${typeTag[c.card_type] || ''}">${c.card_type}</span>
                    ${c.element ? '<span class="card-tag ' + (elemTag[c.element]||'') + '">' + c.element + '</span>' : ''}
                    ${c.is_multi_purpose ? '<span class="card-tag tag-react">MULTI-PURPOSE</span>' : ''}
                </div>
                ${statsHtml}
                <div class="card-detail">
                    ${effectsHtml}
                    ${tutorHtml}
                    ${sacHtml}
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
            'element': card_def.element.name if card_def.element else None,
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
            'tutor_target': card_def.tutor_target,
            'discard_cost_tribe': card_def.discard_cost_tribe,
        })
    return jsonify(cards)

# ---------------------------------------------------------------------------
# Cloud Training Monitor
# ---------------------------------------------------------------------------

def _discover_pods():
    """Discover active RunPod pods with SSH access."""
    try:
        import runpod
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("RUNPOD_API_KEY=") and not line.startswith("#"):
                    runpod.api_key = line.split("=", 1)[1].strip()

        pods = []
        for pod in runpod.get_pods():
            pid = pod["id"]
            name = pod.get("name", pid)
            full = runpod.get_pod(pid)
            cost = full.get("costPerHr", 0)
            runtime = full.get("runtime") or {}
            ports = runtime.get("ports") or []
            ssh_ip = ssh_port = None
            for p in ports:
                if p.get("privatePort") == 22 and p.get("isIpPublic"):
                    ssh_ip = p["ip"]
                    ssh_port = p["publicPort"]
            method = "unknown"
            for m in ["default", "largebatch", "highent", "aggressive", "exploration", "low_lr"]:
                if m in name.lower().replace("_", "").replace("-", ""):
                    method = {"largebatch": "large_batch", "highent": "high_entropy"}.get(m, m)
                    break
            pods.append({
                "id": pid, "name": name, "method": method,
                "ssh_ip": ssh_ip, "ssh_port": ssh_port, "cost_per_hr": cost,
            })
        return pods
    except Exception as e:
        return []


def _ssh_cmd(ip, port, cmd, timeout=15):
    """Run a command on a pod via SSH. Returns stdout or empty string."""
    if not ip or not port:
        return ""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             "-p", str(port), f"root@{ip}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _pull_snapshots(pod):
    """Download snapshots.json from a pod (tensor engine format). Returns data or None."""
    if not pod.get("ssh_ip"):
        return None
    local = CLOUD_DB_DIR / f"{pod['id']}_snapshots.json"
    try:
        subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             "-P", str(pod["ssh_port"]),
             f"root@{pod['ssh_ip']}:/root/output/snapshots.json", str(local)],
            capture_output=True, timeout=30,
        )
        if local.exists() and local.stat().st_size > 0:
            return json.loads(local.read_text())
    except Exception:
        pass
    # Fallback: try training.db (old Python engine format)
    local_db = CLOUD_DB_DIR / f"{pod['id']}.db"
    try:
        subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             "-P", str(pod["ssh_port"]),
             f"root@{pod['ssh_ip']}:/root/output/training.db", str(local_db)],
            capture_output=True, timeout=30,
        )
        if local_db.exists() and local_db.stat().st_size > 0:
            return _read_old_db(local_db)
    except Exception:
        pass
    return None


def _read_old_db(path):
    """Read snapshots from old SQLite format, return as list of dicts."""
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM win_rate_snapshots ORDER BY timestep").fetchall()
        conn.close()
        return [{"timestep": r["timestep"], "win_rate": r["win_rate"]} for r in rows]
    except Exception:
        return None


# Background data cache — page loads instantly, data fetched async
_cloud_cache = {"data": [], "updated": 0, "fetching": False}
_cache_lock = threading.Lock()


def _fetch_cloud_data_bg():
    """Background worker: fetch data from all pods, update cache."""
    with _cache_lock:
        if _cloud_cache["fetching"]:
            return
        _cloud_cache["fetching"] = True

    try:
        pods = _discover_pods()
        results = []

        def fetch_pod_data(pod):
            info = dict(pod)
            gpu_raw = _ssh_cmd(
                pod["ssh_ip"], pod["ssh_port"],
                "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"
            )
            if gpu_raw:
                try:
                    parts = gpu_raw.split(", ")
                    info["gpu_util"] = int(parts[0])
                    info["mem_used_mb"] = int(parts[1])
                    info["mem_total_mb"] = int(parts[2])
                    info["temp_c"] = int(parts[3])
                except (ValueError, IndexError):
                    pass

            # Pull snapshots (tensor engine or old DB format)
            snapshots = _pull_snapshots(pod)
            if snapshots:
                latest = snapshots[-1] if snapshots else {}
                # Estimate games from steps (avg ~100 steps per game with 2 players)
                total_steps = latest.get("timestep", 0)
                est_games = total_steps // 100
                info["data"] = {
                    "snapshots": snapshots,
                    "stats": {"run": {
                        "total_games": est_games,
                        "win_rate": latest.get("win_rate", 0),
                        "fps": latest.get("fps", 0),
                    }},
                }
            else:
                info["data"] = {"snapshots": [], "stats": {}}

            # Try both log filenames
            log = _ssh_cmd(
                pod["ssh_ip"], pod["ssh_port"],
                "tail -n 3 /root/output/tensor_train.log 2>/dev/null || tail -n 3 /root/output/train.log 2>/dev/null"
            )
            info["log_tail"] = log

            # Get FPS from log
            fps_line = _ssh_cmd(
                pod["ssh_ip"], pod["ssh_port"],
                "grep 'fps' /root/output/tensor_train.log 2>/dev/null | tail -1"
            )
            if fps_line and "fps" in fps_line:
                try:
                    fps_str = fps_line.split("fps")[1].split("|")[0].strip().replace(",", "")
                    info["fps"] = int(float(fps_str))
                except (ValueError, IndexError):
                    pass

            results.append(info)

        threads = [threading.Thread(target=fetch_pod_data, args=(p,)) for p in pods]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with _cache_lock:
            _cloud_cache["data"] = results
            _cloud_cache["updated"] = time.time()
    finally:
        with _cache_lock:
            _cloud_cache["fetching"] = False


@app.route('/cloud')
def cloud_page():
    # Kick off background fetch on first visit
    if _cloud_cache["updated"] == 0:
        threading.Thread(target=_fetch_cloud_data_bg, daemon=True).start()
    return render_template_string(CLOUD_TEMPLATE)


@app.route('/api/cloud/pods')
def api_cloud_pods():
    """Return cached pod data instantly, trigger background refresh."""
    age = time.time() - _cloud_cache["updated"]
    # Refresh if cache is older than 45 seconds
    if age > 45 and not _cloud_cache["fetching"]:
        threading.Thread(target=_fetch_cloud_data_bg, daemon=True).start()
    return jsonify({
        "pods": _cloud_cache["data"],
        "cache_age_s": int(age),
        "fetching": _cloud_cache["fetching"],
    })


CLOUD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grid Tactics — Cloud Training Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-bottom: 2px solid #0f3460; padding: 20px 40px; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 24px; color: #00d4ff; letter-spacing: 1px; }
        .header .subtitle { color: #888; font-size: 14px; }
        .nav { display: flex; gap: 20px; }
        .nav a { color: #aaa; text-decoration: none; padding: 8px 16px; border-radius: 6px; transition: all 0.2s; font-size: 14px; }
        .nav a:hover, .nav a.active { color: #00d4ff; background: rgba(0,212,255,0.1); }
        .container { max-width: 1400px; margin: 0 auto; padding: 30px 40px; }
        .status-bar { display: flex; gap: 20px; margin-bottom: 24px; flex-wrap: wrap; }
        .status-item { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px 20px; flex: 1; min-width: 150px; }
        .status-item .label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        .status-item .value { font-size: 28px; font-weight: 700; color: #fff; margin-top: 4px; }
        .status-item .value.green { color: #4caf50; }
        .status-item .value.cyan { color: #00d4ff; }
        .status-item .value.red { color: #f44336; }
        .status-item .value.yellow { color: #ff9800; }
        .pod-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .pod-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px; }
        .pod-card h3 { color: #00d4ff; font-size: 16px; margin-bottom: 4px; }
        .pod-card .method { color: #888; font-size: 13px; margin-bottom: 16px; }
        .gpu-bar { background: #2a2a4a; border-radius: 6px; height: 32px; position: relative; overflow: hidden; margin: 8px 0; }
        .gpu-bar-fill { height: 100%; border-radius: 6px; transition: width 0.5s; display: flex; align-items: center; padding: 0 12px; font-size: 13px; font-weight: 600; color: #fff; }
        .gpu-low { background: linear-gradient(90deg, #f44336, #ff5722); }
        .gpu-mid { background: linear-gradient(90deg, #ff9800, #ffc107); }
        .gpu-high { background: linear-gradient(90deg, #4caf50, #66bb6a); }
        .stat-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #1e1e35; font-size: 14px; }
        .stat-row:last-child { border-bottom: none; }
        .stat-row .label { color: #888; }
        .stat-row .value { color: #fff; font-weight: 600; }
        .chart-container { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px; margin-bottom: 20px; }
        .chart-container h3 { color: #00d4ff; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
        canvas { width: 100% !important; height: 300px !important; }
        .log-box { background: #12121f; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px 16px; font-family: monospace; font-size: 12px; color: #aaa; white-space: pre-wrap; margin-top: 12px; max-height: 80px; overflow: hidden; }
        .refresh-info { text-align: center; color: #555; font-size: 12px; margin-top: 20px; }
        .loading { text-align: center; padding: 60px; color: #666; }
        .loading .spinner { border: 3px solid #2a2a4a; border-top: 3px solid #00d4ff; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 16px; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4" async></script>
</head>
<body>
    <div class="header">
        <div>
            <h1>GRID TACTICS TCG</h1>
            <div class="subtitle">Cloud Training Monitor</div>
        </div>
        <div class="nav">
            <a href="/">Local</a>
            <a href="/cloud" class="active">Cloud</a>
            <a href="/cards">Cards</a>
        </div>
    </div>
    <div class="container" id="app">
        <div class="loading"><div class="spinner"></div>Connecting to pods...</div>
    </div>
    <script>
    let winRateChart = null;

    async function loadCloud() {
        const app = document.getElementById('app');
        let result, pods;
        try {
            const resp = await fetch('/api/cloud/pods');
            result = await resp.json();
            pods = result.pods || [];
        } catch(e) {
            app.innerHTML = '<div class="loading">Failed to connect. Retrying...</div>';
            setTimeout(loadCloud, 10000);
            return;
        }

        const cacheAge = result.cache_age_s || 0;
        const fetching = result.fetching || false;

        if (pods.length === 0 && cacheAge < 5) {
            app.innerHTML = `<div class="loading">
                <div class="spinner"></div>
                Fetching data from pods... (first load takes ~15s)
            </div>`;
            setTimeout(loadCloud, 3000);
            return;
        }

        if (pods.length === 0) {
            app.innerHTML = `<div class="loading" style="animation:none">
                <h2 style="color:#444;margin-bottom:12px">No Active Pods</h2>
                <p style="color:#666">Launch training first:</p>
                <p style="margin-top:8px"><code style="background:#1a1a2e;padding:4px 10px;border-radius:4px;color:#00d4ff">python manage_pods.py launch --gpu 4090</code></p>
            </div>`;
            setTimeout(loadCloud, 15000);
            return;
        }

        // Summary stats
        let totalCost = 0, totalGames = 0, bestWR = 0, bestMethod = '-';
        pods.forEach(p => {
            totalCost += p.cost_per_hr || 0;
            const data = p.data || {};
            Object.values(data.stats || {}).forEach(s => {
                totalGames += s.total_games || 0;
                const wr = s.win_rate || 0;
                if (wr > bestWR) { bestWR = wr; bestMethod = p.method; }
            });
        });

        let html = `
        <div class="status-bar">
            <div class="status-item"><div class="label">Active Pods</div><div class="value cyan">${pods.length}</div></div>
            <div class="status-item"><div class="label">Burn Rate</div><div class="value yellow">$${totalCost.toFixed(2)}/hr</div></div>
            <div class="status-item"><div class="label">Total Games</div><div class="value">${totalGames.toLocaleString()}</div></div>
            <div class="status-item"><div class="label">Best Win Rate</div><div class="value green">${(bestWR*100).toFixed(1)}%</div></div>
            <div class="status-item"><div class="label">Best Method</div><div class="value cyan">${bestMethod}</div></div>
        </div>`;

        // Win rate chart
        html += `<div class="chart-container"><h3>Win Rate Comparison — All Methods</h3><canvas id="winRateCanvas"></canvas></div>`;

        // Pod cards
        html += '<div class="pod-grid">';
        pods.forEach(p => {
            const gpuUtil = p.gpu_util !== undefined ? p.gpu_util : -1;
            const gpuClass = gpuUtil >= 50 ? 'gpu-high' : gpuUtil >= 15 ? 'gpu-mid' : 'gpu-low';
            const gpuLabel = gpuUtil >= 0 ? gpuUtil + '% GPU' : 'N/A';
            const gpuWidth = gpuUtil >= 0 ? Math.max(gpuUtil, 5) : 5;
            const memUsed = p.mem_used_mb || 0;
            const memTotal = p.mem_total_mb || 1;
            const temp = p.temp_c || 0;

            const data = p.data || {};
            const runs = data.runs || [];
            const snapshots = data.snapshots || [];
            const stats = data.stats || {};

            let latestWR = '-', totalG = 0, avgLen = '-';
            if (snapshots.length > 0) {
                latestWR = ((snapshots[snapshots.length-1].win_rate || 0) * 100).toFixed(1) + '%';
            }
            Object.values(stats).forEach(s => {
                totalG += s.total_games || 0;
                if (s.avg_game_length) avgLen = Math.round(s.avg_game_length);
            });

            const latestStep = snapshots.length > 0 ? snapshots[snapshots.length-1].timestep : 0;

            html += `
            <div class="pod-card">
                <h3>${p.name}</h3>
                <div class="method">${p.method} | $${(p.cost_per_hr||0).toFixed(2)}/hr | ${p.id}</div>
                <div class="gpu-bar"><div class="gpu-bar-fill ${gpuClass}" style="width:${gpuWidth}%">${gpuLabel}</div></div>
                <div style="font-size:12px;color:#666;margin-bottom:12px">VRAM: ${memUsed}/${memTotal} MB | ${temp}°C</div>
                <div class="stat-row"><span class="label">Win Rate (eval)</span><span class="value" style="color:${parseFloat(latestWR)>=50?'#4caf50':'#f44336'}">${latestWR}</span></div>
                <div class="stat-row"><span class="label">Games Played</span><span class="value">${totalG.toLocaleString()}</span></div>
                <div class="stat-row"><span class="label">Avg Game Length</span><span class="value">${avgLen} turns</span></div>
                <div class="stat-row"><span class="label">Training Step</span><span class="value">${latestStep.toLocaleString()}</span></div>
                ${p.log_tail ? '<div class="log-box">' + p.log_tail + '</div>' : ''}
            </div>`;
        });
        html += '</div>';

        const ageStr = cacheAge < 60 ? cacheAge + 's ago' : Math.floor(cacheAge/60) + 'm ago';
        const fetchStr = fetching ? ' | <span style="color:#ff9800">updating...</span>' : '';
        html += '<div class="refresh-info">Data: ' + ageStr + fetchStr + ' | Auto-refreshes every 15s | <a href="#" onclick="loadCloud();return false" style="color:#00d4ff">Refresh now</a></div>';

        app.innerHTML = html;

        // Draw chart
        drawWinRateChart(pods);

        // Auto-refresh (fast since it reads from cache)
        setTimeout(loadCloud, 15000);
    }

    function drawWinRateChart(pods) {
        const canvas = document.getElementById('winRateCanvas');
        if (!canvas || typeof Chart === 'undefined') return;

        const datasets = [];
        const colors = ['#00d4ff', '#4caf50', '#ff9800', '#f44336', '#ce93d8', '#ffeb3b'];

        pods.forEach((p, i) => {
            const snapshots = (p.data || {}).snapshots || [];
            if (snapshots.length === 0) return;
            datasets.push({
                label: p.name + ' (' + p.method + ')',
                data: snapshots.map(s => ({ x: s.timestep, y: (s.win_rate || 0) * 100 })),
                borderColor: colors[i % colors.length],
                backgroundColor: 'transparent',
                borderWidth: 2,
                pointRadius: 3,
                tension: 0.3,
            });
        });

        if (winRateChart) winRateChart.destroy();

        winRateChart = new Chart(canvas, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'linear',
                        title: { display: true, text: 'Training Steps', color: '#888' },
                        ticks: { color: '#666' },
                        grid: { color: '#1e1e35' },
                    },
                    y: {
                        min: 0, max: 100,
                        title: { display: true, text: 'Win Rate %', color: '#888' },
                        ticks: { color: '#666' },
                        grid: { color: '#1e1e35' },
                    }
                },
                plugins: {
                    legend: { labels: { color: '#ccc' } },
                    annotation: {
                        annotations: {
                            baseline: {
                                type: 'line', yMin: 50, yMax: 50,
                                borderColor: '#555', borderDash: [6, 4], borderWidth: 1,
                                label: { display: true, content: 'Random (50%)', color: '#666', position: 'start' }
                            }
                        }
                    }
                }
            }
        });
    }

    loadCloud();
    </script>
</body>
</html>
"""


if __name__ == '__main__':
    print("=" * 50)
    print("  Grid Tactics TCG - Dashboard")
    print("  Local:  http://localhost:5000")
    print("  Cloud:  http://localhost:5000/cloud")
    print("=" * 50)
    # host=0.0.0.0 makes it accessible from phone on same network
    app.run(debug=True, port=5000, host='0.0.0.0')
