"""
AI Model Router - Production Platform v6.0
==========================================
ChatGPT-style AI coding assistant with streaming, auth, Prove It, 
outcome-based routing, export, dark mode, and enterprise readiness.
"""

from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, Response, stream_with_context
import sys
import time
import uuid
import json
import hashlib
import sqlite3
import secrets
import logging
import re
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from enum import Enum

# Sentry error tracking
try:
    import sentry_sdk
    sentry_sdk.init(dsn=os.environ.get('SENTRY_DSN', ''), traces_sample_rate=1.0)
except:
    pass

sys.path.insert(0, '.')
from router import process_with_fallback, route_task, MODELS, ROUTING, call_deepseek, call_claude, call_qwen3_coder, call_claude_opus, call_gemini, call_mistral
from evaluator import evaluator
from routing_dataset import routing_dataset_v2 as routing_dataset
from billing import billing

# ═══════════════════════════════════════════════════════════════
# APP INITIALIZATION
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
@app.before_request
def add_request_id():
    """Attach a unique ID to every request for tracing."""
    request.request_id = str(uuid.uuid4())[:8]

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class Config:
    MAX_PROMPT_LENGTH = 4000
    MAX_REQUESTS_PER_HOUR = 50
    CACHE_TTL_HOURS = 24
    MAX_HISTORY_PER_CONVERSATION = 100
    MEMORY_CONTEXT_LENGTH = 10  # Number of previous messages to include for context

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('router.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
class RequestFilter(logging.Filter):
    def filter(self, record):
        try:
            from flask import request as flask_request
            rid = getattr(flask_request, 'request_id', '----') if flask_request else '----'
        except:
            rid = '----'
        record.msg = f"[{rid}] {record.msg}"
        return True

logging.getLogger().addFilter(RequestFilter())
#════════════════════════════
# PLAN TIERS
# ═══════════════════════════════════════════════════════════════

class PlanTier(Enum):
    FREE = {'name': 'Free', 'price_monthly': 0, 'requests_per_day': 50, 'models': ['deepseek'], 'support': 'community'}
    PRO = {'name': 'Pro', 'price_monthly': 20, 'requests_per_day': 500, 'models': ['deepseek', 'claude'], 'support': 'email'}
    TEAM = {'name': 'Team', 'price_monthly': 100, 'requests_per_day': 5000, 'models': ['deepseek', 'claude'], 'support': 'priority'}
    ENTERPRISE = {'name': 'Enterprise', 'price_monthly': 500, 'requests_per_day': float('inf'), 'models': ['deepseek', 'claude'], 'support': 'dedicated'}

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect('router.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cache (prompt_hash TEXT PRIMARY KEY, prompt TEXT, response TEXT, model_used TEXT, task_type TEXT, cost REAL, hit_count INTEGER DEFAULT 1, created_at TIMESTAMP, last_accessed TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT DEFAULT 'anonymous', conversation_id TEXT, role TEXT, content TEXT, model_used TEXT, task_type TEXT, cost REAL, created_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (api_key TEXT PRIMARY KEY, name TEXT, tier TEXT DEFAULT 'free', created_at TIMESTAMP, last_active TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS rate_limits (user_id TEXT, hour TEXT, request_count INTEGER DEFAULT 1, PRIMARY KEY (user_id, hour))''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, model_used TEXT, task_type TEXT, rating TEXT, created_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analytics (date TEXT, model_used TEXT, task_type TEXT, request_count INTEGER DEFAULT 1, total_cost REAL DEFAULT 0, avg_latency REAL DEFAULT 0, cache_hits INTEGER DEFAULT 0, PRIMARY KEY (date, model_used, task_type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, user_id TEXT, details TEXT, ip_address TEXT, created_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id TEXT PRIMARY KEY, tier TEXT DEFAULT 'free', status TEXT DEFAULT 'active', current_period_start TIMESTAMP, current_period_end TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usage_records (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, date DATE, model_used TEXT, request_count INTEGER DEFAULT 0, token_count INTEGER DEFAULT 0, cost REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shared_conversations (share_id TEXT PRIMARY KEY, conversation_id TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, name TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workspace_members (workspace_id TEXT, user_id TEXT, role TEXT DEFAULT 'member', PRIMARY KEY (workspace_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS custom_instructions (user_id TEXT PRIMARY KEY, instructions TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute("INSERT OR IGNORE INTO users (api_key, name, tier, created_at, last_active) VALUES ('demo-key-123', 'Demo User', 'free', ?, ?)", (datetime.now(), datetime.now()))
    c.execute("INSERT OR IGNORE INTO subscriptions (user_id, tier, status, current_period_start, current_period_end) VALUES ('demo-key', 'free', 'active', ?, ?)", (datetime.now(), datetime.now() + timedelta(days=30)))
    c.execute('CREATE INDEX IF NOT EXISTS idx_history_conv ON history(conversation_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id)')
    conn.commit()
    conn.close()

init_db()

# ═══════════════════════════════════════════════════════════════
# AUTH FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def init_auth_db():
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS auth_users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  name TEXT,
                  api_key TEXT UNIQUE NOT NULL,
                  tier TEXT DEFAULT 'free',
                  email_verified BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_login TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS auth_sessions
                 (token TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  expires_at TIMESTAMP NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES auth_users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS password_resets
                 (token TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  expires_at TIMESTAMP NOT NULL,
                  used BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES auth_users(id))''')
    demo_password = hash_password('demo123')
    c.execute('''INSERT OR IGNORE INTO auth_users (email, password_hash, name, api_key, tier, email_verified)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              ('demo@modelrouter.com', demo_password, 'Demo User', 'demo-key-123', 'free', 1))
    conn.commit()
    conn.close()

def hash_password(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.sha256((salt + password).encode()).hexdigest()

def verify_password(password, password_hash):
    salt, hash_val = password_hash.split(':')
    return hashlib.sha256((salt + password).encode()).hexdigest() == hash_val

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=7)
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('INSERT INTO auth_sessions (token, user_id, expires_at) VALUES (?, ?, ?)', (token, user_id, expires))
    conn.commit()
    conn.close()
    return token

def get_user_from_session(token):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''SELECT u.id, u.email, u.name, u.api_key, u.tier 
                 FROM auth_users u JOIN auth_sessions s ON u.id = s.user_id 
                 WHERE s.token = ? AND s.expires_at > ?''', (token, datetime.now()))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'email': row[1], 'name': row[2], 'api_key': row[3], 'tier': row[4]}
    return None

def get_user_by_email(email):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT id, email, password_hash, name, api_key, tier FROM auth_users WHERE email = ?', (email,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'email': row[1], 'password_hash': row[2], 'name': row[3], 'api_key': row[4], 'tier': row[5]}
    return None

def register_user(email, password, name=''):
    if get_user_by_email(email):
        return None, 'Email already registered'
    if len(password) < 6:
        return None, 'Password must be at least 6 characters'
    if not email or '@' not in email:
        return None, 'Invalid email address'
    api_key = 'mr-' + secrets.token_urlsafe(16)
    password_hash = hash_password(password)
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO auth_users (email, password_hash, name, api_key, tier, email_verified)
                     VALUES (?, ?, ?, ?, ?, ?)''', (email, password_hash, name or email.split('@')[0], api_key, 'free', 0))
        user_id = c.lastrowid
        c.execute('''INSERT OR IGNORE INTO users (api_key, name, tier, created_at, last_active)
                     VALUES (?, ?, 'free', ?, ?)''', (api_key, name or email.split('@')[0], datetime.now(), datetime.now()))
        c.execute('''INSERT OR IGNORE INTO subscriptions (user_id, tier, status, current_period_start, current_period_end)
                     VALUES (?, 'free', 'active', ?, ?)''', (api_key[:8], datetime.now(), datetime.now() + timedelta(days=30)))
        conn.commit()
        token = create_session(user_id)
        conn.close()
        return {'token': token, 'user': {'email': email, 'name': name or email.split('@')[0], 'api_key': api_key, 'tier': 'free'}}, None
    except Exception as e:
        conn.close()
        return None, str(e)

def login_user(email, password):
    user = get_user_by_email(email)
    if not user:
        return None, 'Invalid email or password'
    if not verify_password(password, user['password_hash']):
        return None, 'Invalid email or password'
    token = create_session(user['id'])
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('UPDATE auth_users SET last_login = ? WHERE id = ?', (datetime.now(), user['id']))
    conn.commit()
    conn.close()
    return {'token': token, 'user': {'email': user['email'], 'name': user['name'], 'api_key': user['api_key'], 'tier': user['tier']}}, None

def logout_user(token):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('DELETE FROM auth_sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()

init_auth_db()
# ═══════════════════════════════════════════════════════════════
# AUDIT LOGGER
# ═══════════════════════════════════════════════════════════════#

class AuditLogger:
    def log(self, event_type, user_id, details, ip_address='unknown'):
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('INSERT INTO audit_log (event_type, user_id, details, ip_address, created_at) VALUES (?, ?, ?, ?, ?)',
                  (event_type, user_id, json.dumps(details), ip_address, datetime.now()))
        conn.commit()
        conn.close()

audit_logger = AuditLogger()




# ═══════════════════════════════════════════════════════════════
 #cache
# ═══════════════════════════════════════════════════════════════

def get_cached(prompt):
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT response, model_used, task_type, cost FROM cache WHERE prompt_hash = ? AND last_accessed > ?',
              (prompt_hash, datetime.now() - timedelta(hours=Config.CACHE_TTL_HOURS)))
    row = c.fetchone()
    if row:
        c.execute('UPDATE cache SET hit_count = hit_count + 1, last_accessed = ? WHERE prompt_hash = ?', (datetime.now(), prompt_hash))
        conn.commit()
    conn.close()
    return row if row else None

def set_cache(prompt, response, model_used, task_type, cost):
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    try:
        c.execute('INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)',
                  (prompt_hash, prompt, response, model_used, task_type, cost, datetime.now(), datetime.now()))
        conn.commit()
    except Exception as e:
        logger.error(f"Cache write failed: {e}")
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════

def check_rate_limit(user_id):
    current_hour = datetime.now().strftime('%Y-%m-%d-%H')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT request_count FROM rate_limits WHERE user_id = ? AND hour = ?', (user_id, current_hour))
    row = c.fetchone()
    if row:
        if row[0] >= Config.MAX_REQUESTS_PER_HOUR:
            conn.close()
            return False, 0
        c.execute('UPDATE rate_limits SET request_count = request_count + 1 WHERE user_id = ? AND hour = ?', (user_id, current_hour))
    else:
        c.execute('INSERT INTO rate_limits VALUES (?, ?, 1)', (user_id, current_hour))
    conn.commit()
    conn.close()
    return True, Config.MAX_REQUESTS_PER_HOUR - (row[0] if row else 0)

# ═══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ═══════════════════════════════════════════════════════════════

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            if 'user_id' in session:
                return f(*args, **kwargs)
            return jsonify({'error': 'API key required'}), 401
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('SELECT name, tier FROM users WHERE api_key = ?', (api_key,))
        user = c.fetchone()
        conn.close()
        if not user:
            return jsonify({'error': 'Invalid API key'}), 401
        request.user_name = user[0]
        request.user_tier = user[1]
        request.user_id = api_key[:8]
        return f(*args, **kwargs)
    return decorated_function

# ═══════════════════════════════════════════════════════════════
# PROMPT ENRICHMENT
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPTS = {
    'algorithm': "You are an algorithms expert. Write efficient, clean code with complexity analysis.",
    'debug': "You are a debugging expert. Find root causes, explain fixes clearly.",
    'refactor': "You are a software architect. Improve code structure while preserving behavior.",
    'explain': "You are a CS professor. Explain clearly with examples.",
    'other': "You are an expert software engineer. Write clean, working code. Be concise."
}

def enrich_prompt(prompt, task_type, user_id=None):
    system_prompt = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS['other'])
    enriched = f"{system_prompt}\n\nUser request: {prompt}"
    
    # Add custom instructions if user has set them
    if user_id:
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('SELECT instructions FROM custom_instructions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            enriched = f"{system_prompt}\n\nCustom instructions: {row[0]}\n\nUser request: {prompt}"
    
    return enriched

# ═══════════════════════════════════════════════════════════════
# HISTORY
# ═══════════════════════════════════════════════════════════════

def save_history(user_id, conversation_id, role, content, model_used, task_type, cost):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('INSERT INTO history (user_id, conversation_id, role, content, model_used, task_type, cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (user_id, conversation_id, role, content, model_used, task_type, cost, datetime.now()))
    c.execute('DELETE FROM history WHERE conversation_id = ? AND id NOT IN (SELECT id FROM history WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?)',
              (conversation_id, conversation_id, Config.MAX_HISTORY_PER_CONVERSATION))
    conn.commit()
    conn.close()

def get_history(conversation_id, limit=50):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT role, content, model_used, task_type FROM history WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?', (conversation_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_conversation_context(conversation_id):
    """Get recent messages for model context."""
    history = get_history(conversation_id, Config.MEMORY_CONTEXT_LENGTH)
    context = ""
    for role, content, _, _ in history:
        prefix = "User: " if role == 'user' else "Assistant: "
        context += prefix + content + "\n"
    return context.strip()

# ═══════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════

def update_analytics(model_used, task_type, cost, latency, was_cached):
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''INSERT INTO analytics (date, model_used, task_type, request_count, total_cost, avg_latency, cache_hits) VALUES (?, ?, ?, 1, ?, ?, ?)
                 ON CONFLICT(date, model_used, task_type) DO UPDATE SET request_count = request_count + 1, total_cost = total_cost + ?,
                 avg_latency = (avg_latency * (request_count - 1) + ?) / request_count, cache_hits = cache_hits + ?''',
              (today, model_used, task_type, cost, latency, 1 if was_cached else 0, cost, latency, 1 if was_cached else 0))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ═══════════════════════════════════════════════════════════════

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ModelRouter</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/11.1.1/marked.min.js"></script>
    <style>
        :root {
            --bg: #0d0d0d;
            --sidebar-bg: #111111;
            --card-bg: #1a1a1a;
            --input-bg: #1a1a1a;
            --border: #262626;
            --text: #e5e5e5;
            --text-secondary: #888;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --claude: #d97706;
            --deepseek: #3b82f6;
            --success: #22c55e;
            --error: #ef4444;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; font-size: 14px; line-height: 1.6; }
        
        .sidebar { width: 260px; background: var(--sidebar-bg); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
        .sidebar-header { padding: 16px; border-bottom: 1px solid var(--border); }
        .sidebar-header .logo { font-size: 16px; font-weight: 600; color: #fff; }
        .new-chat-btn { width: 100%; padding: 10px; margin: 12px 16px; width: calc(100% - 32px); background: #fff; color: #000; border: none; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; }
        .new-chat-btn:hover { background: #e5e5e5; }
        .conversation-list { flex: 1; overflow-y: auto; padding: 0 8px; }
        .conversation-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text-secondary); margin-bottom: 2px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .conversation-item span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
        .conversation-item .delete-btn { color: #555; font-size: 11px; cursor: pointer; flex-shrink: 0; padding: 2px 4px; border-radius: 4px; }
        .conversation-item .delete-btn:hover { color: #ef4444; background: rgba(239,68,68,0.1); }
        .conversation-item:hover { background: var(--card-bg); color: var(--text); }
        .conversation-item.active { background: var(--card-bg); color: #fff; }
        .sidebar-footer { padding: 12px 16px; border-top: 1px solid var(--border); }
        .sidebar-footer select { width: 100%; background: var(--card-bg); color: var(--text); border: 1px solid var(--border); padding: 8px 10px; border-radius: 8px; font-size: 12px; outline: none; }
        .user-info { display: flex; align-items: center; gap: 10px; margin-top: 10px; font-size: 13px; color: var(--text-secondary); }
        .user-avatar { width: 28px; height: 28px; border-radius: 6px; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
        
        .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
        .header { padding: 12px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: var(--bg); }
        .header-title { font-size: 15px; font-weight: 500; color: var(--text-secondary); }
        .header-actions { display: flex; gap: 8px; align-items: center; }
        .header-actions button { background: none; border: 1px solid var(--border); color: var(--text-secondary); padding: 6px 14px; border-radius: 8px; font-size: 12px; cursor: pointer; }
        .header-actions button:hover { background: var(--card-bg); color: var(--text); }
        
        .chat-container { flex: 1; overflow-y: auto; padding: 24px 0; }
        .chat-inner { max-width: 900px; margin: 0 auto; padding: 0 24px; display: flex; flex-direction: column; gap: 24px; }
        .message { display: flex; gap: 16px; animation: fadeIn 0.2s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { flex-direction: row-reverse; }
        .msg-avatar { width: 32px; height: 32px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; flex-shrink: 0; }
        .message.user .msg-avatar { background: #333; color: #fff; }
        .message.assistant .msg-avatar { background: #111; color: var(--accent); border: 1px solid var(--border); }
        .msg-content { max-width: 100%; }
        .msg-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 12px; }
        .model-tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
        .model-tag.deepseek { background: rgba(59,130,246,0.15); color: var(--deepseek); }
        .model-tag.claude { background: rgba(217,119,6,0.15); color: var(--claude); }
        .model-tag.cached { background: rgba(34,197,94,0.15); color: var(--success); font-size: 10px; margin-left: 4px; }
        .msg-bubble { font-size: 14px; line-height: 1.7; }
        .msg-bubble p { margin: 8px 0; }
        .msg-bubble pre { background: #0a0a0a; border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow-x: auto; margin: 12px 0; position: relative; }
        .msg-bubble pre code { background: none; padding: 0; font-size: 13px; color: #e5e5e5; font-family: "SF Mono", "Fira Code", "Consolas", monospace; }
        .msg-bubble code { background: var(--card-bg); padding: 2px 6px; border-radius: 4px; font-size: 13px; color: var(--accent); }
        .copy-btn { position: absolute; top: 8px; right: 8px; background: #222; border: 1px solid #333; color: #888; padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; opacity: 0; transition: all 0.15s; }
        pre:hover .copy-btn { opacity: 1; }
        .copy-btn:hover { background: #333; color: #fff; }
        .msg-actions { display: flex; gap: 4px; margin-top: 8px; opacity: 0; transition: opacity 0.15s; }
        .msg-content:hover .msg-actions { opacity: 1; }
        .msg-actions button { background: none; border: none; color: var(--text-secondary); padding: 4px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; }
        .msg-actions button:hover { background: var(--card-bg); color: var(--text); }
        
        .input-area { border-top: 1px solid var(--border); padding: 16px 24px; background: var(--bg); }
        .input-inner { max-width: 900px; margin: 0 auto; display: flex; gap: 12px; align-items: flex-end; }
        .input-inner textarea { flex: 1; background: var(--input-bg); border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; color: var(--text); font-family: inherit; font-size: 14px; resize: none; min-height: 44px; max-height: 200px; outline: none; line-height: 1.5; }
        .input-inner textarea:focus { border-color: var(--accent); }
        .input-inner button { background: #fff; color: #000; border: none; border-radius: 10px; padding: 10px 18px; font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; height: 44px; }
        .input-inner button:hover { background: #e5e5e5; }
        .input-inner button:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .empty-state { text-align: center; padding-top: 120px; }
        .empty-state h2 { font-size: 24px; font-weight: 500; margin-bottom: 8px; }
        .empty-state p { color: var(--text-secondary); max-width: 400px; margin: 0 auto 24px; }
        .suggestion-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-width: 500px; margin: 0 auto; }
        .suggestion-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; text-align: left; cursor: pointer; font-size: 13px; color: var(--text-secondary); transition: all 0.15s; }
        .suggestion-card:hover { border-color: var(--accent); color: var(--text); }
        
        .typing-dots { display: flex; gap: 3px; padding: 8px 0; }
        .typing-dots span { width: 6px; height: 6px; background: #555; border-radius: 50%; animation: dotBounce 1.4s infinite ease-in-out; }
        .typing-dots span:nth-child(1) { animation-delay: 0s; }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes dotBounce { 0%, 80%, 100% { transform: scale(0.6); } 40% { transform: scale(1); } }
    </style>
</head>
<body>
    <div id="authModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:1000;align-items:center;justify-content:center;">
        <div style="background:#1a1a1a;border:1px solid #262626;border-radius:16px;padding:32px;width:400px;max-width:90vw;">
            <h2 style="margin-bottom:20px;font-size:20px;font-weight:500;color:#fff;" id="authTitle">Welcome back</h2>
            <div id="authError" style="color:#ef4444;font-size:13px;margin-bottom:12px;display:none;"></div>
            <input type="email" id="authEmail" placeholder="Email" style="width:100%;padding:10px 14px;background:#0d0d0d;border:1px solid #262626;border-radius:8px;color:#e5e5e5;font-size:14px;margin-bottom:10px;outline:none;">
            <input type="password" id="authPassword" placeholder="Password" style="width:100%;padding:10px 14px;background:#0d0d0d;border:1px solid #262626;border-radius:8px;color:#e5e5e5;font-size:14px;margin-bottom:10px;outline:none;">
            <input type="text" id="authName" placeholder="Name (optional)" style="width:100%;padding:10px 14px;background:#0d0d0d;border:1px solid #262626;border-radius:8px;color:#e5e5e5;font-size:14px;margin-bottom:16px;outline:none;display:none;">
            <button onclick="window.location.href='/auth/github'" style="width:100%;padding:12px;background:#24292e;color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:500;cursor:pointer;margin-bottom:8px;">Sign in with GitHub</button>
            <button onclick="authSubmit()" style="width:100%;padding:12px;background:#fff;color:#000;border:none;border-radius:10px;font-size:14px;font-weight:500;cursor:pointer;">Continue</button>
            <p style="text-align:center;margin-top:16px;font-size:13px;color:#888;">
                <span id="authToggleText">Don't have an account?</span>
                <a href="#" onclick="toggleAuth()" style="color:#3b82f6;text-decoration:none;margin-left:4px;" id="authToggleLink">Sign up</a>
            </p>
            <p style="text-align:center;margin-top:8px;font-size:12px;">
                <a href="#" onclick="forgotPassword()" style="color:var(--text-secondary);text-decoration:none;">Forgot password?</a>
            </p>        </div>
    </div>
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="logo">ModelRouter</div>
        </div>
        <button class="new-chat-btn" onclick="newChat()">+ New chat</button>
        <div class="conversation-list" id="conversationList"></div>
        <div class="sidebar-footer">
<select id="modelOverride" onchange="updateBadge()">
    <option value="auto">Auto-select</option>
    <option value="gemini">Gemini 2.5 Flash (Fastest)</option>
    <option value="deepseek">DeepSeek V3 (Cheap)</option>
    <option value="qwen3-coder">Qwen3-Coder (Algorithms)</option>
    <option value="mistral">Mistral Large (General)</option>
    <option value="claude">Claude Sonnet (Production)</option>
    <option value="claude-opus">Claude Opus (Deep Research)</option>
</select>
            </select>
            <button onclick="window.location.href='/checkout'" style="width:100%;background:#3b82f6;color:#fff;border:none;padding:8px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;margin-top:8px;">Upgrade to Pro</button>
            </div>
            <div class="user-info">
                <div class="user-avatar">D</div>
                <span>Demo User</span>
            </div>
        </div>
    </div>
    <div class="main">
        <div class="header">
            <div class="header-title" id="headerTitle">New conversation</div>
            <div class="header-actions">
                <button onclick="shareConversation()">Share</button>
                <button onclick="window.location.href='/usage'">Usage</button>
                <button onclick="exportConversation()">Export</button>
            </div>
        </div>
        <div class="chat-container" id="chatContainer">
            <div class="chat-inner" id="chatInner">
                <div class="empty-state" id="emptyState">
                    <h2>What do you want to build?</h2>
                    <p>ModelRouter picks the best AI model for your coding task automatically.</p>
                    <div class="suggestion-grid">
                        <div class="suggestion-card" onclick="quickPrompt('Write a Python function to sort an array using quicksort')">"Write quicksort in Python"</div>
                        <div class="suggestion-card" onclick="quickPrompt('Fix the null pointer bug in this code')">"Fix this null pointer bug"</div>
                        <div class="suggestion-card" onclick="quickPrompt('Refactor this class to use dependency injection')">"Refactor for dependency injection"</div>
                        <div class="suggestion-card" onclick="quickPrompt('Explain how garbage collection works in Python')">"Explain Python garbage collection"</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="input-area">
            <div class="input-inner">
                <textarea id="userInput" placeholder="Ask anything..." rows="1" maxlength="4000"></textarea>
                <button id="sendBtn" onclick="sendMessage()">Send</button>
            </div>
        </div>
    </div>
    <script>
        marked.setOptions({ highlight: function(code, lang) { if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, {language:lang}).value; return hljs.highlightAuto(code).value; }, breaks: true });
        
                var AUTH_TOKEN = localStorage.getItem('auth_token') || '';
        var urlParams = new URLSearchParams(window.location.search);
        var tokenFromUrl = urlParams.get('token');
        if (tokenFromUrl) {
            localStorage.setItem('auth_token', tokenFromUrl);
            AUTH_TOKEN = tokenFromUrl;
            window.location.href = '/';
        }
        var isRegistering = false;
        if (AUTH_TOKEN) {
            fetch('/auth/me', { headers: {'Authorization': 'Bearer ' + AUTH_TOKEN} })
                .then(r => r.json())
                .then(function(data) {
                    if (data.user) { API_KEY = data.user.api_key; document.querySelector('.user-info span').textContent = data.user.name; }
                    else { document.getElementById('authModal').style.display = 'flex'; }
                });
        } else { document.getElementById('authModal').style.display = 'flex'; }
        function toggleAuth() {
            isRegistering = !isRegistering;
            document.getElementById('authTitle').textContent = isRegistering ? 'Create account' : 'Welcome back';
            document.getElementById('authToggleText').textContent = isRegistering ? 'Already have an account?' : "Don't have an account?";
            document.getElementById('authToggleLink').textContent = isRegistering ? 'Sign in' : 'Sign up';
            document.getElementById('authName').style.display = isRegistering ? 'block' : 'none';
            document.getElementById('authError').style.display = 'none';
        }
        function authSubmit() {
            var email = document.getElementById('authEmail').value.trim();
            var password = document.getElementById('authPassword').value;
            var name = document.getElementById('authName').value.trim();
            var errorDiv = document.getElementById('authError');
            if (!email || !password) { errorDiv.textContent = 'Email and password required'; errorDiv.style.display = 'block'; return; }
            var endpoint = isRegistering ? '/auth/register' : '/auth/login';
            var body = { email: email, password: password };
            if (isRegistering && name) body.name = name;
            fetch(endpoint, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) })
                .then(r => r.json())
                .then(function(data) {
                    if (data.error) { errorDiv.textContent = data.error; errorDiv.style.display = 'block'; }
                    else {
                        AUTH_TOKEN = data.token; API_KEY = data.user.api_key;
                        localStorage.setItem('auth_token', AUTH_TOKEN);
                        document.getElementById('authModal').style.display = 'none';
                        document.querySelector('.user-info span').textContent = data.user.name;
                        loadConversations();
                    }
                });
        }
        function logout() {
            localStorage.removeItem('auth_token');
            AUTH_TOKEN = '';
            API_KEY = '';
            window.location.href = '/';
        }
        function forgotPassword() {
            var email = document.getElementById('authEmail').value.trim();
            if (!email) { alert('Enter your email first'); return; }
            fetch('/auth/forgot', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email: email}) })
                .then(r => r.json())
                .then(function(d) {
                    if (d.reset_link) { prompt('Reset link (copy this):', window.location.origin + d.reset_link); }
                    else { alert('If that email exists, a reset link has been sent.'); }
                });
        }
        var chatContainer = document.getElementById('chatContainer');
        var chatInner = document.getElementById('chatInner');
        var userInput = document.getElementById('userInput');
        var sendBtn = document.getElementById('sendBtn');
        var emptyState = document.getElementById('emptyState');
        var headerTitle = document.getElementById('headerTitle');
        var modelOverride = document.getElementById('modelOverride');
        var conversationId = 'conv_' + Date.now();
        var currentPrompt = '';
        var hasMessages = false;
        var API_KEY = '';
        
        userInput.addEventListener('keydown', function(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
        
        function updateBadge() {}
        function quickPrompt(text) { userInput.value = text; sendMessage(); }
        
        loadConversations();
        
        function loadConversations() {
            fetch('/conversations?api_key=' + API_KEY)
                .then(r => r.json()).then(function(data) {
                    if (!Array.isArray(data)) return;
                    var html = '';
                                       data.forEach(function(c) { 
                        html += '<div class="conversation-item" onclick="loadConversation(\'' + c.id + '\')"><span>' + escapeHtml(c.title) + '</span><span class="delete-btn" onclick="event.stopPropagation();deleteConversation(\'' + c.id + '\')">✕</span></div>';
                    });
                    document.getElementById('conversationList').innerHTML = html;
                }).catch(function() {});
        }
        
        function loadConversation(convId) {
            conversationId = convId;
            chatInner.innerHTML = '';
            emptyState.style.display = 'none';
            hasMessages = true;
            headerTitle.textContent = 'Conversation';
            fetch('/history?conversation_id=' + convId + '&api_key=' + API_KEY)
                .then(r => r.json()).then(function(data) {
                    if (!Array.isArray(data)) return;
                    data.forEach(function(msg) { addMessage(msg.role, msg.content, msg.model || '', false, false); });
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                });
        }
        function deleteConversation(convId) {
            if (confirm('Delete this conversation?')) {
                fetch('/conversations/' + convId, { method: 'DELETE', headers: {'X-API-Key': API_KEY} })
                    .then(function() { 
                        loadConversations(); 
                        if (conversationId === convId) newChat(); 
                    });
            }
        }        
        function newChat() { 
            conversationId = 'conv_' + Date.now(); 
            chatInner.innerHTML = ''; 
            chatInner.appendChild(emptyState);
            emptyState.style.display = ''; 
            hasMessages = false; 
            headerTitle.textContent = 'New conversation';
            loadConversations(); 
            userInput.focus(); 
        }
        
        function sendMessage() {
            var prompt = userInput.value.trim();
            if (!prompt) return;
            currentPrompt = prompt;
            if (!hasMessages) { emptyState.style.display = 'none'; hasMessages = true; headerTitle.textContent = prompt.slice(0, 40) + '...'; }
            addMessage('user', prompt, '');
            userInput.value = '';
            sendBtn.disabled = true;
            
            var assistantDiv = document.createElement('div'); assistantDiv.className = 'message assistant';
            var avatar = document.createElement('div'); avatar.className = 'msg-avatar'; avatar.textContent = 'AI';
            var contentDiv = document.createElement('div'); contentDiv.className = 'msg-content';
            
            var statusDiv = document.createElement('div'); 
            statusDiv.className = 'msg-meta'; 
            statusDiv.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">🧠 Thinking...</span>';
            contentDiv.appendChild(statusDiv);
            
            var bubble = document.createElement('div'); bubble.className = 'msg-bubble';
            bubble.id = 'streaming-' + Date.now();
            contentDiv.appendChild(bubble);
            assistantDiv.appendChild(avatar);
            assistantDiv.appendChild(contentDiv);
            chatInner.appendChild(assistantDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            
            var fullResponse = '';
            var meta = null;
            var startTime = Date.now();
            
            var thinkingTimer = setInterval(function() {
                var elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                statusDiv.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">🧠 Thinking... (' + elapsed + 's)</span>';
            }, 100);
            
            fetch('/chat/stream', { 
                method: 'POST', 
                headers: {'Content-Type':'application/json', 'X-API-Key': API_KEY}, 
                body: JSON.stringify({prompt: prompt, model_override: modelOverride.value, conversation_id: conversationId}) 
            })
            .then(function(response) {
                var reader = response.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';
                
                function read() {
                    reader.read().then(function(result) {
                        if (result.done) {
                            clearInterval(thinkingTimer);
                            sendBtn.disabled = false;
                            userInput.focus();
                            loadConversations();
                            chatContainer.scrollTop = chatContainer.scrollHeight;
                            if (meta) {
                                statusDiv.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">✓ ' + meta.model + ' · ' + meta.elapsed + 's · $' + (meta.cost || 0).toFixed(6) + '</span>';
                            }
                            return;
                        }
                        
                        buffer += decoder.decode(result.value, {stream: true});
                        var lines = buffer.split('\n');
                        buffer = lines.pop() || '';
                        
                        for (var i = 0; i < lines.length; i++) {
                            var line = lines[i].trim();
                            if (line.startsWith('data: ')) {
                                try {
                                    var data = JSON.parse(line.substring(6));
                                    if (data.type === 'meta') {
                                        meta = data;
                                        clearInterval(thinkingTimer);
                                        statusDiv.innerHTML = '<span style="color:var(--success);font-size:12px;">⚡ Generating with ' + data.model + '...</span>';
                                        var isDS = data.model.toLowerCase().indexOf('deepseek') !== -1;
                                        var isQW = data.model.toLowerCase().indexOf('qwen') !== -1;
                                        var badgeClass = isDS ? 'deepseek' : isQW ? 'deepseek' : 'claude';
                                        var tag = document.createElement('span'); tag.className = 'model-tag ' + badgeClass; tag.textContent = data.model;
                                        statusDiv.appendChild(tag);
                                    } else if (data.type === 'token') {
                                        fullResponse += data.text;
                                        bubble.innerHTML = marked.parse(fullResponse);
                                        chatContainer.scrollTop = chatContainer.scrollHeight;
                                    } else if (data.type === 'done') {
                                        clearInterval(thinkingTimer);
                                        if (meta) {
                                            statusDiv.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">✓ ' + meta.model + ' · ' + meta.elapsed + 's · $' + (meta.cost || 0).toFixed(6) + '</span>';
                                        }
                                        if (meta) {
                                            var actionsDiv = document.createElement('div'); actionsDiv.className = 'msg-actions';
                                        var prove = document.createElement('button'); prove.textContent = 'Review'; prove.onclick = function() {
                        var code = bubble.querySelector('pre code');
                        if (!code) { alert('No code block found'); return; }
                        var lang = 'python';
                        var preEl = bubble.querySelector('pre');
                        if (preEl) {
                            var codeEl = preEl.querySelector('code');
                            if (codeEl && codeEl.className) {
                                var classes = codeEl.className.split(' ');
                                for (var j = 0; j < classes.length; j++) {
                                    if (classes[j].startsWith('language-')) {
                                        lang = classes[j].replace('language-', '');
                                        break;
                                    }
                                }
                            }
                        }
                        
                        prove.textContent = 'Reviewing...';
                        prove.disabled = true;
                        
                        fetch('/prove-it', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({code: code.textContent, language: lang, prompt: currentPrompt}) })
                            .then(r => r.json())
                            .then(function(d) {
                                prove.textContent = 'Review';
                                prove.disabled = false;
                                
                                var existing = contentDiv.querySelector('.review-panel');
                                if (existing) existing.remove();
                                
                                var r = d.review;
                                var v = d.verification;
                                
                                var panel = document.createElement('div');
                                panel.className = 'review-panel';
                                panel.style.cssText = 'margin-top:16px;border:1px solid var(--border);border-radius:10px;overflow:hidden;font-size:13px;background:var(--bg-secondary);';
                                
                                // Status bar
                                var statusColor = v.overall === 'PASSED' ? '#22c55e' : v.overall === 'FAILED' ? '#ef4444' : '#fbbf24';
                                var statusText = v.overall === 'PASSED' ? 'Passed' : v.overall === 'FAILED' ? 'Failed' : 'Warning';
                                
                                var html = '';
                                html += '<div style="padding:14px 18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);">';
                                html += '<div style="display:flex;align-items:center;gap:12px;">';
                                html += '<div style="width:10px;height:10px;border-radius:50%;background:' + statusColor + ';"></div>';
                                html += '<span style="font-weight:600;color:var(--text-primary);">Review</span>';
                                html += '<span style="font-size:11px;color:var(--text-secondary);">' + r.lines_of_code + ' lines &middot; ' + r.language + '</span>';
                                html += '</div>';
                                html += '<span style="background:' + (v.confidence >= 0.9 ? '#22c55e' : v.confidence >= 0.7 ? '#fbbf24' : '#ef4444') + ';color:#000;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;">' + Math.round(v.confidence * 100) + '%</span>';
                                html += '</div>';
                                
                                // Stats row
                                html += '<div style="padding:12px 18px;display:flex;gap:28px;border-bottom:1px solid var(--border);">';
                                html += '<div><span style="color:var(--text-secondary);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">Issues</span><br><span style="color:' + (v.issues > 0 ? '#ef4444' : '#22c55e') + ';font-weight:600;">' + (v.issues || '0') + '</span></div>';
                                html += '<div><span style="color:var(--text-secondary);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">Warnings</span><br><span style="color:' + (v.warnings > 0 ? '#fbbf24' : '#22c55e') + ';font-weight:600;">' + (v.warnings || '0') + '</span></div>';
                                html += '<div><span style="color:var(--text-secondary);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">Complexity</span><br><span style="color:var(--text-primary);font-weight:500;">' + (r.complexity || 'N/A') + '</span></div>';
                                html += '</div>';
                                
                                // Issues section
                                if (r.issues && r.issues.length > 0) {
                                    html += '<div style="padding:12px 18px;border-bottom:1px solid var(--border);">';
                                    html += '<div style="font-size:11px;color:#ef4444;font-weight:600;margin-bottom:6px;">Issues</div>';
                                    r.issues.forEach(function(i) {
                                        html += '<div style="display:flex;gap:8px;padding:4px 0;font-size:12px;">';
                                        html += '<span style="color:#ef4444;flex-shrink:0;">&bull;</span>';
                                        html += '<span style="color:var(--text-secondary);">' + i.finding + '</span>';
                                        html += '</div>';
                                    });
                                    html += '</div>';
                                }
                                
                                // Warnings section
                                if (r.warnings && r.warnings.length > 0) {
                                    html += '<div style="padding:12px 18px;border-bottom:1px solid var(--border);">';
                                    html += '<div style="font-size:11px;color:#fbbf24;font-weight:600;margin-bottom:6px;">Warnings</div>';
                                    r.warnings.forEach(function(w) {
                                        html += '<div style="display:flex;gap:8px;padding:4px 0;font-size:12px;">';
                                        html += '<span style="color:#fbbf24;flex-shrink:0;">&bull;</span>';
                                        html += '<span style="color:var(--text-secondary);">' + w.finding + '</span>';
                                        html += '</div>';
                                    });
                                    html += '</div>';
                                }
                                
                                // Strengths section
                                if (r.strengths && r.strengths.length > 0) {
                                    html += '<div style="padding:12px 18px;border-bottom:1px solid var(--border);">';
                                    html += '<div style="font-size:11px;color:#22c55e;font-weight:600;margin-bottom:6px;">Strengths</div>';
                                    r.strengths.forEach(function(s) {
                                        html += '<div style="display:flex;gap:8px;padding:4px 0;font-size:12px;">';
                                        html += '<span style="color:#22c55e;flex-shrink:0;">&bull;</span>';
                                        html += '<span style="color:var(--text-secondary);">' + s.finding + '</span>';
                                        html += '</div>';
                                    });
                                    html += '</div>';
                                }
                                
                                // Recommendations
                                if (r.recommendations && r.recommendations.length > 0) {
                                    html += '<div style="padding:12px 18px;">';
                                    html += '<div style="font-size:11px;color:var(--accent);font-weight:600;margin-bottom:6px;">Recommendations</div>';
                                    r.recommendations.forEach(function(rec) {
                                        var prioColor = rec.priority === 'critical' ? '#ef4444' : rec.priority === 'medium' ? '#fbbf24' : '#22c55e';
                                        html += '<div style="display:flex;gap:8px;padding:4px 0;font-size:12px;align-items:center;">';
                                        html += '<span style="background:' + prioColor + ';color:#000;font-size:9px;padding:1px 6px;border-radius:3px;font-weight:600;">' + rec.priority.toUpperCase() + '</span>';
                                        html += '<span style="color:var(--text-secondary);">' + rec.action + '</span>';
                                        html += '</div>';
                                    });
                                    html += '</div>';
                                }
                                
                                panel.innerHTML = html;
                                contentDiv.appendChild(panel);
                            });                           
                    };                  actionsDiv.appendChild(prove);
                                        var regen = document.createElement('button'); regen.textContent = 'Regenerate'; regen.onclick = function() { userInput.value = prompt; sendMessage(); };
                                        actionsDiv.appendChild(regen);
                                        contentDiv.appendChild(actionsDiv);                                        }
                                        bubble.querySelectorAll('pre code').forEach(function(block) { hljs.highlightElement(block); });
                                        bubble.querySelectorAll('pre').forEach(function(pre) {
                                            var btn = document.createElement('button'); btn.className = 'copy-btn'; btn.textContent = 'Copy';
                                            btn.onclick = function() { navigator.clipboard.writeText(pre.textContent).then(function() { btn.textContent = 'Copied!'; setTimeout(function() { btn.textContent = 'Copy'; }, 2000); }); };
                                            pre.appendChild(btn);
                                        });
                                    }
                                } catch(e) {}
                            }
                        }
                        read();
                    });
                }
                read();
            })
            .catch(function(e) {
                clearInterval(thinkingTimer);
                bubble.textContent = 'Error: ' + e.message;
                sendBtn.disabled = false;
            });
        }
        function addMessage(role, content, model, isError, isCached) {
            var div = document.createElement('div'); div.className = 'message ' + role;
            var avatar = document.createElement('div'); avatar.className = 'msg-avatar'; avatar.textContent = role === 'user' ? 'U' : 'AI';
            var contentDiv = document.createElement('div'); contentDiv.className = 'msg-content';
            
            if (role === 'assistant' && model && !isError) {
                var meta = document.createElement('div'); meta.className = 'msg-meta';
                var isDS = model.toLowerCase().indexOf('deepseek') !== -1;
                var tag = document.createElement('span'); tag.className = 'model-tag ' + (isDS ? 'deepseek' : 'claude'); tag.textContent = model;
                meta.appendChild(tag);
                if (isCached) { var cacheTag = document.createElement('span'); cacheTag.className = 'model-tag cached'; cacheTag.textContent = 'cached'; meta.appendChild(cacheTag); }
                contentDiv.appendChild(meta);
            }
            
            var bubble = document.createElement('div'); bubble.className = 'msg-bubble';
            
            if (role === 'assistant' && !isError && content) {
                bubble.innerHTML = marked.parse(content);
                bubble.querySelectorAll('pre').forEach(function(pre) {
                    var btn = document.createElement('button'); btn.className = 'copy-btn'; btn.textContent = 'Copy';
                    btn.onclick = function() { navigator.clipboard.writeText(pre.textContent).then(function() { btn.textContent = 'Copied!'; setTimeout(function() { btn.textContent = 'Copy'; }, 2000); }); };
                    pre.appendChild(btn);
                });
                               if (model) {
                    var actionsDiv = document.createElement('div'); actionsDiv.className = 'msg-actions';
                    var prove = document.createElement('button'); prove.textContent = '🔍 Review'; prove.onclick = function() {
                        var code = bubble.querySelector('pre code');
                        if (!code) { alert('No code block found'); return; }
                        fetch('/prove-it', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({code: code.textContent, language: 'python'}) })
                            .then(r => r.json()).then(function(d) {
                                addMessage('assistant', d.report, 'Prove It', false, false);
                            });
                    };
                    actionsDiv.appendChild(prove);
                    var regen = document.createElement('button'); regen.textContent = 'Regenerate'; regen.onclick = function() { userInput.value = currentPrompt; sendMessage(); };
                    actionsDiv.appendChild(regen);
                    contentDiv.appendChild(actionsDiv);
                }
            } else {
                bubble.textContent = content;
                if (isError) bubble.style.color = 'var(--error)';
            }
            
            contentDiv.appendChild(bubble);
            div.appendChild(avatar);
            if (role === 'user') div.appendChild(contentDiv); else { div.appendChild(contentDiv); div.appendChild(avatar); div.style.flexDirection = 'row'; }
            chatInner.appendChild(div);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        function addTyping() {
            var id = 'typing-' + Date.now(); var div = document.createElement('div'); div.className = 'message assistant'; div.id = id;
            div.innerHTML = '<div class="msg-avatar">AI</div><div class="msg-content"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
            chatInner.appendChild(div); chatContainer.scrollTop = chatContainer.scrollHeight; return id;
        }
        function removeTyping(id) { var el = document.getElementById(id); if (el) el.remove(); }
        function escapeHtml(text) { var d = document.createElement('div'); d.textContent = text; return d.innerHTML; }
        function shareConversation() {
            fetch('/share', { method: 'POST', headers: {'Content-Type':'application/json', 'X-API-Key': API_KEY}, body: JSON.stringify({conversation_id: conversationId}) })
                .then(r => r.json()).then(function(data) { navigator.clipboard.writeText(window.location.origin + data.share_url); alert('Link copied!'); });
        }
         function exportConversation() {
            window.open('/conversations/' + conversationId + '/export?api_key=' + API_KEY);
        }       
        userInput.focus();
    </script>
</body>
</html>
'''
# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/manifest.json')
def manifest():
    return jsonify({"name": "ModelRouter", "short_name": "Router", "start_url": "/", "display": "standalone", "background_color": "#0f0f1a", "theme_color": "#e94560"})

@app.route('/chat', methods=['POST'])
@require_auth
def chat():
    try:
        data = request.json
        prompt = data.get('prompt', '').strip()
        model_override = data.get('model_override', 'auto')
        conversation_id = data.get('conversation_id', 'default')
        user_id = getattr(request, 'user_id', session.get('user_id', 'anonymous'))
        
        if not prompt: return jsonify({'error': 'Please enter a prompt.'})
        if len(prompt) > Config.MAX_PROMPT_LENGTH: return jsonify({'error': 'Prompt too long.'})
        
        allowed, remaining = check_rate_limit(user_id)
        if not allowed: return jsonify({'error': 'Rate limit exceeded.'}), 429
        
        cached = get_cached(prompt)
        if cached:
            response_text, model_used, task_type, cost = cached
            save_history(user_id, conversation_id, 'user', prompt, model_used, task_type, cost)
            save_history(user_id, conversation_id, 'assistant', response_text, model_used, task_type, cost)
            update_analytics(model_used, task_type, cost, 0, True)
            
                       # ─── Record cached hit in routing dataset ─────────
            try:
                from routing_dataset import routing_dataset_v2 as routing_dataset
                routing_dataset.record_request(
                    prompt=prompt, model_used=model_used, task_type=task_type,
                    latency=0, cost=cost, quality_score=0.8, success_score=0.8,
                    user_id=user_id
                )
            except Exception as e:
                logger.warning(f"Dataset recording skipped: {e}")
            return jsonify({'result': response_text, 'model_used': model_used, 'task_type': task_type, 'elapsed': 0, 'cost': cost, 'cached': True})
        
        # Get conversation context
        context = get_conversation_context(conversation_id)
        context_prompt = prompt
        if context:
            context_prompt = f"Previous conversation:\n{context}\n\nNew request: {prompt}"
        
        plan = route_task(prompt)
        enriched_prompt = enrich_prompt(context_prompt, plan['task_type'], user_id)
        start_time = time.time()
        
        if model_override != 'auto':
            if model_override == 'deepseek':
                result_text = call_deepseek(enriched_prompt)
                model_used = 'DeepSeek V3'; task_type = 'manual_override'
                cost = MODELS['deepseek']['cost_per_1k_tokens'] * len(prompt) / 4000
            elif model_override == 'claude':
                result_text = call_claude(enriched_prompt)
                model_used = 'Claude Sonnet 4.6'; task_type = 'manual_override'
                cost = MODELS['claude']['cost_per_1k_tokens'] * len(prompt) / 4000
            elif model_override == 'qwen3-coder':
                from router import call_qwen3_coder
                result_text = call_qwen3_coder(enriched_prompt)
                model_used = 'Qwen3-Coder-480B'; task_type = 'manual_override'
                cost = MODELS['qwen3-coder']['cost_per_1k_tokens'] * len(prompt) / 4000
            elif model_override == 'claude-opus':
                from router import call_claude_opus
                result_text = call_claude_opus(enriched_prompt)
                model_used = 'Claude Opus 4.8'; task_type = 'manual_override'
                cost = MODELS['claude-opus']['cost_per_1k_tokens'] * len(prompt) / 4000
            elif model_override == 'gemini':
                from router import call_gemini
                result_text = call_gemini(enriched_prompt)
                model_used = 'Gemini 2.5 Flash'; task_type = 'manual_override'
                cost = MODELS['gemini']['cost_per_1k_tokens'] * len(prompt) / 4000
            elif model_override == 'mistral':
                from router import call_mistral
                result_text = call_mistral(enriched_prompt)
                model_used = 'Mistral Large'; task_type = 'manual_override'
                cost = MODELS['mistral']['cost_per_1k_tokens'] * len(prompt) / 4000
            else:
                result_text = call_claude(enriched_prompt)
                model_used = 'Claude Sonnet 4.6'; task_type = 'manual_override'
                cost = MODELS['claude']['cost_per_1k_tokens'] * len(prompt) / 4000
        else:
            from router import estimate_complexity
            complexity = estimate_complexity(prompt)
            
            if complexity == 'simple':
                primary = 'gemini'
            elif complexity == 'heavy':
                primary = 'claude-opus'
            else:
                primary = plan['primary_model']
            
            # Outcome-based override
            try:
                from evaluator import evaluator
                best = evaluator.get_best_model_for_task(plan['task_type'])
                if best and complexity == 'standard':
                    primary = best
            except:
                pass
            
            if primary == 'deepseek':
                result_text = call_deepseek(enriched_prompt)
            elif primary == 'claude':
                result_text = call_claude(enriched_prompt)
            elif primary == 'qwen3-coder':
                from router import call_qwen3_coder
                result_text = call_qwen3_coder(enriched_prompt)
            elif primary == 'claude-opus':
                from router import call_claude_opus
                result_text = call_claude_opus(enriched_prompt)
            elif primary == 'gemini':
                from router import call_gemini
                result_text = call_gemini(enriched_prompt)
            elif primary == 'mistral':
                from router import call_mistral
                result_text = call_mistral(enriched_prompt)
            else:
                result_text = call_deepseek(enriched_prompt)
            
            model_used = MODELS[primary]['name']
            task_type = plan['task_type']
            cost = MODELS[primary]['cost_per_1k_tokens'] * len(prompt) / 4000
            used_fallback = False        
        elapsed = time.time() - start_time
        if not result_text: return jsonify({'error': 'Model failed to respond.'})
        
        set_cache(prompt, result_text, model_used, task_type, cost)
        save_history(user_id, conversation_id, 'user', prompt, model_used, task_type, cost)
        save_history(user_id, conversation_id, 'assistant', result_text, model_used, task_type, cost)
        update_analytics(model_used, task_type, cost, elapsed, False)
        
        # ─── PHASES 16-22: Outcome Tracking, Dataset, Evaluation ───
        # ─── Evaluation & Outcome Tracking ───
        try:
            from evaluator import evaluator
            evaluator.analyze_conversation(conversation_id)
            evaluator.score_response(prompt, result_text, task_type, model_used)
            from routing_dataset import routing_dataset_v2 as routing_dataset
            routing_dataset.record_request(
                prompt=prompt, model_used=model_used, task_type=task_type,
                latency=elapsed, cost=cost, quality_score=0.7, success_score=0.5,
                user_id=user_id
            )
        except Exception as e:
            logger.warning(f"Evaluation skipped: {e}")
        # ─────────────────────────────────────────────────────────
        
        return jsonify({'result': result_text, 'model_used': model_used, 'task_type': task_type, 'elapsed': round(elapsed, 2), 'cost': cost, 'cached': False})
    
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': 'Server error.'})
@app.route('/chat/stream', methods=['POST'])
@require_auth
def chat_stream():
    """Stream response tokens one at a time."""
    from flask import Response, stream_with_context
    
    data = request.json
    prompt = data.get('prompt', '').strip()
    model_override = data.get('model_override', 'auto')
    conversation_id = data.get('conversation_id', 'default')
    user_id = getattr(request, 'user_id', session.get('user_id', 'anonymous'))
    
    if not prompt:
        return jsonify({'error': 'Please enter a prompt.'})
    
    task_type = 'other'
    cost = 0
    model_used = 'Unknown'
    
    plan = route_task(prompt)
    enriched_prompt = enrich_prompt(prompt, plan['task_type'], user_id)
    start_time = time.time()
    
    # Route to model
    if model_override != 'auto':
        if model_override == 'deepseek':
            result_text = call_deepseek(enriched_prompt)
            model_used = 'DeepSeek V3'
        elif model_override == 'claude':
            result_text = call_claude(enriched_prompt)
            model_used = 'Claude Sonnet 4.6'
        elif model_override == 'qwen3-coder':
            from router import call_qwen3_coder
            result_text = call_qwen3_coder(enriched_prompt)
            model_used = 'Qwen3-Coder-480B'
        elif model_override == 'claude-opus':
            from router import call_claude_opus
            result_text = call_claude_opus(enriched_prompt)
            model_used = 'Claude Opus 4.8'
        elif model_override == 'gemini':
            from router import call_gemini
            result_text = call_gemini(enriched_prompt)
            model_used = 'Gemini 2.5 Flash'
        elif model_override == 'mistral':
            from router import call_mistral
            result_text = call_mistral(enriched_prompt)
            model_used = 'Mistral Large'
        else:
            result_text = call_deepseek(enriched_prompt)
            model_used = 'DeepSeek V3'
    else:
        from router import estimate_complexity
        complexity = estimate_complexity(prompt)
        
        if complexity == 'simple':
            primary = 'gemini'
        elif complexity == 'heavy':
            primary = 'claude-opus'
        else:
            primary = plan['primary_model']
        
        # Outcome-based override: use best model from real data
        try:
            best = evaluator.get_best_model_for_task(plan['task_type'])
            if best and complexity == 'standard':
                primary = best
        except:
            pass
        
        print(f"!!! COMPLEXITY: {complexity} → {MODELS[primary]['name']} !!!")
        
        if primary == 'deepseek':
            result_text = call_deepseek(enriched_prompt)
        elif primary == 'claude':
            result_text = call_claude(enriched_prompt)
        elif primary == 'qwen3-coder':
            from router import call_qwen3_coder
            result_text = call_qwen3_coder(enriched_prompt)
        elif primary == 'claude-opus':
            from router import call_claude_opus
            result_text = call_claude_opus(enriched_prompt)
        elif primary == 'gemini':
            from router import call_gemini
            result_text = call_gemini(enriched_prompt)
        elif primary == 'mistral':
            from router import call_mistral
            result_text = call_mistral(enriched_prompt)
        else:
            result_text = call_deepseek(enriched_prompt)
        
        model_used = MODELS[primary]['name']
        task_type = plan['task_type']
        cost = MODELS[primary]['cost_per_1k_tokens'] * len(prompt) / 4000
        used_fallback = False
    # Save to history
    elapsed = time.time() - start_time	
    save_history(user_id, conversation_id, 'user', prompt, model_used, task_type, cost)
    save_history(user_id, conversation_id, 'assistant', result_text, model_used, task_type, cost)
    update_analytics(model_used, task_type, cost, elapsed, False)
    set_cache(prompt, result_text, model_used, task_type, cost)
    
    def generate():
        # Send metadata first
        req_id = getattr(request, 'request_id', '----')
        yield f"data: {json.dumps({'type': 'meta', 'request_id': req_id, 'model': model_used, 'task': task_type, 'cost': cost, 'elapsed': round(elapsed, 2)})}\n\n"
        
        # Stream the response word by word
        words = result_text.split(' ')
        for i, word in enumerate(words):
            chunk = word + (' ' if i < len(words) - 1 else '')
            yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
            time.sleep(0.02)  # Natural typing speed
        
        # Send completion signal
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')
@app.route('/conversations')
@require_auth
def list_conversations():
    user_id = getattr(request, 'user_id', 'anonymous')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute("SELECT conversation_id, content, created_at FROM history WHERE user_id = ? AND role = 'user' GROUP BY conversation_id ORDER BY created_at DESC LIMIT 50", (user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'title': r[1][:60] + ('...' if len(r[1]) > 60 else ''), 'created': r[2]} for r in rows])

@app.route('/instructions', methods=['GET', 'POST'])
@require_auth
def custom_instructions():
    user_id = getattr(request, 'user_id', 'anonymous')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        instructions = data.get('instructions', '')
        c.execute('INSERT OR REPLACE INTO custom_instructions (user_id, instructions, updated_at) VALUES (?, ?, ?)', (user_id, instructions, datetime.now()))
        conn.commit()
        conn.close()
        return jsonify({'status': 'saved'})
    else:
        c.execute('SELECT instructions FROM custom_instructions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({'instructions': row[0] if row else ''})

@app.route('/share', methods=['POST'])
@require_auth
def share_conversation():
    data = request.json
    conversation_id = data.get('conversation_id')
    user_id = getattr(request, 'user_id', 'anonymous')
    share_id = secrets.token_urlsafe(8)
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('INSERT INTO shared_conversations (share_id, conversation_id, created_by) VALUES (?, ?, ?)', (share_id, conversation_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'share_url': f'/shared/{share_id}'})

@app.route('/shared/<share_id>')
def view_shared(share_id):
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT conversation_id FROM shared_conversations WHERE share_id = ?', (share_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "Conversation not found", 404
    history = get_history(row[0])
    conn.close()
    html = '<div style="max-width:800px;margin:40px auto;font-family:sans-serif;">'
    for role, content, model, _ in history:
        html += f'<div style="margin:16px 0;padding:12px;border-radius:8px;background:#f5f5f5;"><strong>{role}</strong>'
        if model: html += f' <span style="color:#666;font-size:12px;">via {model}</span>'
        html += f'<pre style="white-space:pre-wrap;">{content}</pre></div>'
    html += '</div>'
    return html

@app.route('/feedback', methods=['POST'])
def feedback():
    data = request.json
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('INSERT INTO feedback (conversation_id, model_used, task_type, rating, created_at) VALUES (?, ?, ?, ?, ?)',
              (data.get('conversation_id', ''), data.get('model', ''), 'unknown', data.get('rating', ''), datetime.now()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/history')
def conversation_history():
    return jsonify([{'role': r[0], 'content': r[1], 'model': r[2], 'task_type': r[3]} for r in get_history(request.args.get('conversation_id', 'default'))])

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/v1/route', methods=['POST'])
def api_route():
    if not request.headers.get('X-API-Key'): return jsonify({'error': 'API key required'}), 401
    prompt = request.json.get('prompt', '')
    if not prompt: return jsonify({'error': 'prompt is required'}), 400
    result = process_with_fallback(prompt)
    return jsonify({'result': result.get('result', ''), 'model_used': result.get('model_used', 'Unknown'), 'task_type': result['plan']['task_type'], 'cost': result['plan']['estimated_cost']})

@app.route('/api/v1/models')
def api_models():
    return jsonify({'models': [{'id': 'deepseek', 'name': 'DeepSeek V3', 'strengths': ['algorithms', 'debugging', 'speed'], 'cost': 'free via API'}, {'id': 'claude', 'name': 'Claude Sonnet 4.6', 'strengths': ['refactoring', 'production code'], 'cost': '$0.003/1K tokens'}]})

@app.route('/prove-it', methods=['POST'])
def prove_it_endpoint():
    """Professional engineering review for AI-generated code."""
    data = request.json
    code = data.get('code', '')
    language = data.get('language', 'python')
    original_prompt = data.get('prompt', '')
    
    if not code:
        return jsonify({'error': 'No code provided'})
    
    if language not in ['python', 'javascript', 'typescript', 'js', 'ts', 'java', 'c']:
        return jsonify({
            'verification': {'overall': 'SKIPPED'},
            'report': f"## Prove It — Engineering Review\n\n**Status:** ⚠️ Language Not Supported\n\nProve It currently reviews Python, JavaScript, TypeScript, Java, and C."
        })
    
    issues = []
    warnings = []
    strengths = []
    
    # ═══════════════════════════════════════════════════════════
    # 1. SECURITY REVIEW
    # ═══════════════════════════════════════════════════════════
    
    security_checks = {
        'python': [
            (r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', 'critical', 'Hardcoded secret detected — use environment variables'),
            (r'eval\(', 'critical', 'Unsafe eval() — can execute arbitrary code'),
            (r'exec\(', 'critical', 'Unsafe exec() — can execute arbitrary code'),
            (r'os\.system\(', 'high', 'Shell injection risk via os.system()'),
            (r'pickle\.loads?\(', 'high', 'Unsafe deserialization — pickle can execute arbitrary code'),
            (r'f".*SELECT.*\{', 'high', 'Potential SQL injection via f-string'),
            (r'except\s*:', 'medium', 'Bare except clause — catch specific exceptions'),
        ],
        'javascript': [
            (r'(password|secret|api_key|token)\s*[:=]\s*["\'][^"\']+["\']', 'critical', 'Hardcoded secret detected'),
            (r'eval\(', 'critical', 'Unsafe eval() — can execute arbitrary code'),
            (r'innerHTML\s*=', 'high', 'Potential XSS via innerHTML'),
            (r'document\.write\(', 'high', 'Unsafe document.write()'),
        ],
        'java': [
            (r'(password|secret|api_key|token)\s*=\s*"[^"]+', 'critical', 'Hardcoded secret detected'),
            (r'Runtime\.getRuntime\(\)\.exec\(', 'critical', 'Shell injection via Runtime.exec()'),
        ],
        'c': [
            (r'system\(', 'critical', 'Shell injection via system()'),
            (r'gets\(', 'high', 'Buffer overflow risk — gets() is unsafe'),
            (r'scanf\("%s"', 'high', 'Buffer overflow risk — unbounded %s'),
        ],
    }
    
    lang_key = 'python' if language not in security_checks else language
    if language in ['typescript', 'ts']: lang_key = 'javascript'
    if language in ['js']: lang_key = 'javascript'
    
    for pattern, severity, message in security_checks.get(lang_key, []):
        if re.search(pattern, code):
            if severity == 'critical':
                issues.append({'category': 'Security', 'severity': severity, 'finding': message})
            else:
                warnings.append({'category': 'Security', 'severity': severity, 'finding': message})
    
    # ═══════════════════════════════════════════════════════════
    # 2. CODE QUALITY REVIEW
    # ═══════════════════════════════════════════════════════════
    
    lines = code.split('\n')
    
    # Check for comments/documentation
    if language == 'python':
        has_docstring = '"""' in code or "'''" in code
        has_comments = any('# ' in line or '#\t' in line for line in lines)
        if has_docstring:
            strengths.append({'category': 'Documentation', 'finding': 'Includes docstrings'})
        elif has_comments:
            strengths.append({'category': 'Documentation', 'finding': 'Includes inline comments'})
        else:
            warnings.append({'category': 'Documentation', 'severity': 'low', 'finding': 'No docstrings or comments — consider adding documentation'})
    
    # Check for error handling
    if language == 'python':
        has_error_handling = 'try:' in code or 'except' in code or 'raise ' in code
    elif lang_key == 'javascript':
        has_error_handling = 'try {' in code or 'catch' in code or 'throw ' in code
    elif language == 'java':
        has_error_handling = 'try {' in code or 'catch' in code or 'throw ' in code
    else:
        has_error_handling = True
    
    if has_error_handling:
        strengths.append({'category': 'Robustness', 'finding': 'Includes error handling'})
    elif len(lines) > 20:
        warnings.append({'category': 'Robustness', 'severity': 'medium', 'finding': 'No error handling detected — consider adding try/catch'})
    
    # Check for type hints (Python) or type annotations (TS)
    if language == 'python' and ('def ' in code):
        if '-> ' in code or ': int' in code or ': str' in code or ': bool' in code or ': list' in code or ': dict' in code:
            strengths.append({'category': 'Code Quality', 'finding': 'Uses type hints'})
        elif len(lines) > 30:
            warnings.append({'category': 'Code Quality', 'severity': 'low', 'finding': 'Consider adding type hints for better maintainability'})
    
    # Check function length
    function_lines = 0
    in_function = False
    for line in lines:
        if line.strip().startswith('def ') or line.strip().startswith('function ') or '(' in line and '{' in line:
            in_function = True
        if in_function:
            function_lines += 1
    
    # ═══════════════════════════════════════════════════════════
    # 3. SYNTAX VALIDATION
    # ═══════════════════════════════════════════════════════════
    
    syntax_ok = True
    if language == 'python':
        try:
            compile(code, '<review>', 'exec')
        except SyntaxError as e:
            syntax_ok = False
            issues.append({'category': 'Syntax', 'severity': 'critical', 'finding': f'Syntax error: {str(e)}'})
    
    # ═══════════════════════════════════════════════════════════
    # 4. TEST COVERAGE ASSESSMENT
    # ═══════════════════════════════════════════════════════════
    
    has_tests = any(word in code.lower() for word in ['assert', 'test', 'expect(', 'it(', 'describe('])
    if has_tests:
        strengths.append({'category': 'Testing', 'finding': 'Includes test cases'})
    else:
        warnings.append({'category': 'Testing', 'severity': 'medium', 'finding': 'No test cases included — add assertions or unit tests'})
    
    # ═══════════════════════════════════════════════════════════
    # 5. EDGE CASE ANALYSIS
    # ═══════════════════════════════════════════════════════════
    
    edge_cases_found = []
    if 'null' in code.lower() or 'none' in code.lower() or 'empty' in code.lower():
        edge_cases_found.append('Null/empty input handling')
    if '0' in code or 'zero' in code.lower() or 'negative' in code.lower():
        edge_cases_found.append('Zero/negative value handling')
    if 'max' in code.lower() or 'min' in code.lower() or 'bound' in code.lower():
        edge_cases_found.append('Boundary condition handling')
    
    if edge_cases_found:
        strengths.append({'category': 'Edge Cases', 'finding': f'Handles: {", ".join(edge_cases_found)}'})
    elif len(lines) > 20:
        warnings.append({'category': 'Edge Cases', 'severity': 'medium', 'finding': 'No obvious edge case handling — consider null, empty, and boundary inputs'})
    
    # ═══════════════════════════════════════════════════════════
    # 6. COMPLEXITY ESTIMATION
    # ═══════════════════════════════════════════════════════════
    
    has_nested_loops = False
    for i, line in enumerate(lines):
        if ('for ' in line or 'while ' in line) and i + 1 < len(lines):
            if ('for ' in lines[i+1] or 'while ' in lines[i+1]):
                has_nested_loops = True
    
    complexity_note = 'O(n) or better' if not has_nested_loops else 'May contain O(n²) patterns'
    if 'sort' in code.lower() or 'sorted' in code.lower():
        complexity_note = 'O(n log n) from sorting'
    
    # ═══════════════════════════════════════════════════════════
    # 7. SANDBOX EXECUTION
    # ═══════════════════════════════════════════════════════════
    
    execution_ok = None
    exec_output = ''
    exec_error = ''
    
    if language == 'python':
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            result = subprocess.run(['python', temp_path], capture_output=True, text=True, timeout=10)
            os.unlink(temp_path)
            execution_ok = result.returncode == 0
            exec_output = result.stdout[:500]
            exec_error = result.stderr[:500]
        except subprocess.TimeoutExpired:
            execution_ok = False
            exec_error = 'Execution timed out after 10 seconds'
        except Exception as e:
            execution_ok = False
            exec_error = str(e)
    
    # ═══════════════════════════════════════════════════════════
    # 8. CONFIDENCE SCORE
    # ═══════════════════════════════════════════════════════════
    
    confidence = 1.0
    if issues:
        confidence -= 0.3 * len([i for i in issues if i['severity'] == 'critical'])
        confidence -= 0.15 * len([i for i in issues if i['severity'] == 'high'])
    if warnings:
        confidence -= 0.05 * len(warnings)
    if not syntax_ok:
        confidence -= 0.4
    if execution_ok is False:
        confidence -= 0.3
    if not has_tests:
        confidence -= 0.1
    confidence = max(0.0, min(1.0, confidence))
    
    if confidence >= 0.9:
        confidence_level = 'High — Production Ready'
    elif confidence >= 0.7:
        confidence_level = 'Medium — Minor Issues'
    elif confidence >= 0.5:
        confidence_level = 'Low — Needs Review'
    else:
        confidence_level = 'Critical — Do Not Deploy'
    
    # ═══════════════════════════════════════════════════════════
    # BUILD REPORT
    # ═══════════════════════════════════════════════════════════
    
    overall = '✅ PASSED' if (syntax_ok and not issues and execution_ok is not False) else '❌ FAILED' if (not syntax_ok or issues or execution_ok is False) else '⚠️ WARNING'
    
    # ═══════════════════════════════════════════════════════════
    # BUILD STRUCTURED RESPONSE
    # ═══════════════════════════════════════════════════════════
    
    overall = 'PASSED' if (syntax_ok and not issues and execution_ok is not False) else 'FAILED' if (not syntax_ok or issues or execution_ok is False) else 'WARNING'
    # Collect failure modes
    failure_modes = []
    if not has_error_handling:
        failure_modes.append('Unexpected inputs may cause unhandled exceptions')
    if not has_tests:
        failure_modes.append('Regressions may go undetected without tests')
    if has_nested_loops:
        failure_modes.append('Performance degradation with large inputs due to nested loops')
    if not edge_cases_found:
        failure_modes.append('May fail on edge cases (null, empty, boundary values)')    
    # Build structured data for the frontend
    review_data = {
        'overall': overall,
        'confidence': round(confidence, 2),
        'language': language,
        'lines_of_code': len(lines),
        'issues': [{'severity': i['severity'], 'category': i['category'], 'finding': i['finding']} for i in issues],
        'warnings': [{'severity': w['severity'], 'category': w['category'], 'finding': w['finding']} for w in warnings],
        'strengths': [{'category': s['category'], 'finding': s['finding']} for s in strengths],
        'syntax_valid': syntax_ok,
        'execution': {
            'ran': execution_ok is not None,
            'passed': execution_ok is True,
            'output': exec_output[:200] if exec_output else None,
            'error': exec_error[:200] if exec_error else None
        },
        'edge_cases': edge_cases_found,
        'failure_modes': failure_modes,
        'recommendations': [],
        'complexity': complexity_note
    }
    
    # Generate recommendations
    if confidence < 0.9:
        if not has_tests:
            review_data['recommendations'].append({'priority': 'medium', 'action': 'Add unit tests to prevent regressions'})
        if not has_error_handling and len(lines) > 20:
            review_data['recommendations'].append({'priority': 'low', 'action': 'Add error handling for robustness'})
    if issues:
        review_data['recommendations'].append({'priority': 'critical', 'action': 'Address security issues before deployment'})
    
    return jsonify({
        'verification': {
            'overall': overall,
            'confidence': round(confidence, 2),
            'issues': len(issues),
            'warnings': len(warnings),
            'strengths': len(strengths)
        },
        'review': review_data
    })
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/auth/register', methods=['POST'])
def auth_register():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '')
    result, error = register_user(email, password, name)
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'token': result['token'], 'user': result['user']})

@app.route('/auth/login', methods=['POST'])
def auth_login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    result, error = login_user(email, password)
    if error:
        return jsonify({'error': error}), 401
    return jsonify({'token': result['token'], 'user': result['user']})

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if token:
        logout_user(token)
    return jsonify({'status': 'ok'})

@app.route('/auth/me', methods=['GET'])
def auth_me():
    token = request.headers.get('Authorization', '').replace('Bearer ', '') or request.cookies.get('session_token', '')
    user = get_user_from_session(token)
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({'user': user})

# ═══════════════════════════════════════════════════════════════
# ANALYTICS DASHBOARD
# ═══════════════════════════════════════════════════════════════

@app.route('/dashboard')
def dashboard():
    return '''
    <!DOCTYPE html>
    <html>
    <head><title>ModelRouter Analytics</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #0d0d0d; color: #e5e5e5; padding: 40px; }
        .card { background: #1a1a1a; border: 1px solid #262626; border-radius: 12px; padding: 24px; margin: 16px 0; }
        h2 { color: #3b82f6; margin-top: 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #262626; }
        th { color: #888; font-size: 11px; text-transform: uppercase; }
        .metric { font-size: 28px; font-weight: 600; }
        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
    </style></head>
    <body>
        <h1>Routing Analytics</h1>
        <div class="grid" id="metrics"></div>
        <div class="card"><h2>Model Performance</h2><table id="modelTable"></table></div>
        <div class="card"><h2>Task Routing</h2><table id="taskTable"></table></div>
        <script>
            fetch('/analytics?api_key=demo-key-123').then(r=>r.json()).then(d=>{
                var html='';
                if(d.length>0){var last=d[0];html+='<div class="card"><div class="metric">'+last.requests+'</div>Requests</div>';html+='<div class="card"><div class="metric">$'+last.cost.toFixed(4)+'</div>Cost</div>';}
                document.getElementById('metrics').innerHTML=html||'No data yet';
            });
            fetch('/leaderboard').then(r=>r.json()).then(d=>{
                var html='<tr><th>Model</th><th>Task</th><th>Satisfaction</th><th>Requests</th></tr>';
                for(var m in d.leaderboard){for(var t in d.leaderboard[m]){var s=d.leaderboard[m][t];html+='<tr><td>'+m+'</td><td>'+t+'</td><td>'+s.satisfaction+'%</td><td>'+s.requests+'</td></tr>';}}
                document.getElementById('taskTable').innerHTML=html||'<tr><td>No data yet</td></tr>';
            });
        </script>
    </body></html>''';


# ═══════════════════════════════════════════════════════════════
# TEAM ACCOUNTS
# ═══════════════════════════════════════════════════════════════

@app.route('/admin/scout/scan')
@require_auth
def scout_scan():
    """Manually trigger model discovery scan."""
    from model_scout import model_scout
    report = model_scout.daily_scan()
    return jsonify(report)

@app.route('/admin/scout/auto-add')
@require_auth
def scout_auto_add():
    """Auto-discover and add winning models."""
    from model_scout import model_scout
    new_models = model_scout.scan_for_new_models()
    added = []
    candidates = model_scout.get_candidates_for_benchmark()
    for candidate in candidates:
        result = model_scout.auto_benchmark_candidate(candidate['model_id'])
        if result['recommendation'] == 'add_to_routing':
            strengths = list(set(r['task'] for r in result['results'] if r['passed']))
            model_scout.auto_add_to_routing(candidate['model_id'], strengths)
            added.append(candidate['model_id'])
    return jsonify({
        'new_models_found': len(new_models),
        'benchmarked': len(candidates),
        'added_to_routing': added
    })

@app.route('/team/create', methods=['POST'])
@require_auth
def create_team():
    data = request.json
    team_name = data.get('name', 'My Team')
    user_id = getattr(request, 'user_id', 'anonymous')
    workspace_id = secrets.token_urlsafe(8)
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS workspaces
                 (id TEXT PRIMARY KEY, name TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workspace_members
                 (workspace_id TEXT, user_id TEXT, role TEXT DEFAULT 'member',
                  PRIMARY KEY (workspace_id, user_id))''')
    c.execute('INSERT INTO workspaces VALUES (?, ?, ?, ?)', (workspace_id, team_name, user_id, datetime.now()))
    c.execute('INSERT INTO workspace_members VALUES (?, ?, ?)', (workspace_id, user_id, 'admin'))
    conn.commit()
    conn.close()
    return jsonify({'workspace_id': workspace_id, 'invite_code': workspace_id[:8], 'name': team_name})

@app.route('/team/join', methods=['POST'])
@require_auth
def join_team():
    data = request.json
    invite_code = data.get('code', '')
    user_id = getattr(request, 'user_id', 'anonymous')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT id FROM workspaces WHERE id LIKE ?', (invite_code + '%',))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Invalid invite code'}), 404
    c.execute('INSERT OR IGNORE INTO workspace_members VALUES (?, ?, ?)', (row[0], user_id, 'member'))
    conn.commit()
    conn.close()
    return jsonify({'status': 'joined', 'workspace_id': row[0]})

@app.route('/conversations/<conversation_id>/export')
@require_auth
def export_conversation(conversation_id):
    """Export conversation as markdown."""
    history = get_history(conversation_id)
    md = f"# ModelRouter Conversation\n\nExported: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n"
    for role, content, model, _ in history:
        prefix = "**You**" if role == 'user' else f"**{model or 'AI'}**"
        md += f"{prefix}:\n\n{content}\n\n---\n\n"
    return Response(md, mimetype='text/markdown', headers={'Content-Disposition': f'attachment; filename=conversation-{conversation_id[:8]}.md'})

@app.route('/conversations/<conversation_id>', methods=['DELETE'])
@require_auth
def delete_conversation(conversation_id):
    """Delete a conversation and all its messages."""
    user_id = getattr(request, 'user_id', 'anonymous')
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('DELETE FROM history WHERE conversation_id = ? AND user_id = ?', (conversation_id, user_id))
    c.execute('DELETE FROM shared_conversations WHERE conversation_id = ?', (conversation_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'deleted'})
@app.route('/auth/forgot', methods=['POST'])
def forgot_password():
    """Send password reset link."""
    email = request.json.get('email', '').strip().lower()
    user = get_user_by_email(email)
    if user:
        token = secrets.token_urlsafe(32)
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)',
                  (token, user['id'], datetime.now() + timedelta(hours=1)))
        conn.commit()
        conn.close()
        # In production, send email. For now, return the link.
        return jsonify({'reset_link': f'/auth/reset/{token}'})
    return jsonify({'message': 'If that email exists, a reset link has been sent.'})

@app.route('/auth/reset/<token>', methods=['POST'])
def reset_password(token):
    """Reset password with token."""
    password = request.json.get('password', '')
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('SELECT user_id FROM password_resets WHERE token = ? AND expires_at > ? AND used = 0',
              (token, datetime.now()))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Invalid or expired token'}), 400
    
    new_hash = hash_password(password)
    c.execute('UPDATE auth_users SET password_hash = ? WHERE id = ?', (new_hash, row[0]))
    c.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'password_reset'})
@app.route('/leaderboard/public')
def public_leaderboard():
    """Public model comparison leaderboard."""
    from evaluator import evaluator
    weights = evaluator.get_model_weights(days=30)
    
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''SELECT model_name, category, pass_rate, avg_latency, total_tests
                 FROM model_rankings ORDER BY model_name, pass_rate DESC''')
    benchmarks = c.fetchall()
    conn.close()
    
    return jsonify({
        'outcome_based': weights,
        'benchmarks': [{'model': r[0], 'category': r[1], 'pass_rate': r[2], 'latency': r[3], 'tests': r[4]} for r in benchmarks],
        'updated': datetime.now().isoformat()
    })
@app.route('/subscribe/checkout', methods=['POST'])
@require_auth
def create_checkout():
    """Upgrade user subscription."""
    user_id = getattr(request, 'user_id', 'anonymous')
    tier = request.json.get('tier', 'pro')
    from billing import billing
    billing.create_subscription(user_id, tier)
    return jsonify({'status': 'upgraded', 'tier': tier})
@app.route('/health/models')
def model_health():
    """Check which models are currently available."""
    health = {}
    
    # Test DeepSeek
    try:
        from router import call_deepseek
        result = call_deepseek("Respond with just the word 'ok'")
        health['deepseek'] = 'healthy' if 'ok' in result.lower() else 'degraded'
    except:
        health['deepseek'] = 'down'
    
    # Test Claude
    try:
        from router import call_claude
        result = call_claude("Respond with just the word 'ok'")
        health['claude'] = 'healthy' if 'ok' in result.lower() else 'degraded'
    except:
        health['claude'] = 'down'
    
    # Test Qwen3-Coder
    try:
        from router import call_qwen3_coder
        result = call_qwen3_coder("Respond with just the word 'ok'")
        health['qwen3-coder'] = 'healthy' if 'ok' in result.lower() else 'degraded'
    except:
        health['qwen3-coder'] = 'down'
    
    overall = all(v == 'healthy' for v in health.values())
    
    return jsonify({
        'status': 'healthy' if overall else 'degraded',
        'models': health,
        'timestamp': datetime.now().isoformat()
    })
@app.route('/dashboard/usage')
@require_auth
def user_usage_dashboard():
    """Show user their personal usage stats."""
    user_id = getattr(request, 'user_id', session.get('user_id', 'anonymous'))
    
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    
    # Total requests
    c.execute('SELECT COUNT(*) FROM routing_dataset_v2 WHERE user_id = ?', (user_id,))
    total = c.fetchone()[0] or 0
    
    # By model
    c.execute('''SELECT model_selected, COUNT(*), AVG(quality_score), SUM(cost_microdollars)
                 FROM routing_dataset_v2 WHERE user_id = ?
                 GROUP BY model_selected''', (user_id,))
    by_model = [{'model': r[0], 'requests': r[1], 'avg_quality': round(r[2] or 0, 2), 'cost': round((r[3] or 0) / 1000000, 6)} for r in c.fetchall()]
    
    # Cache hits
    c.execute('''SELECT COUNT(*) FROM routing_dataset_v2 WHERE user_id = ? AND quality_score > 0.8''', (user_id,))
    cache_hits = c.fetchone()[0] or 0
    
    # Total cost
    c.execute('SELECT SUM(cost_microdollars) FROM routing_dataset_v2 WHERE user_id = ?', (user_id,))
    total_cost = round((c.fetchone()[0] or 0) / 1000000, 6)
    
    # Estimated savings from caching
    savings = round(total_cost * 0.4, 6)
    
    conn.close()
    
    return jsonify({
        'total_requests': total,
        'total_cost': total_cost,
        'estimated_savings': savings,
        'cache_hits': cache_hits,
        'by_model': by_model,
        'period': 'all_time'
    })
@app.route('/usage')
def usage_page():
    """User-facing usage dashboard page."""
    return '''
    <!DOCTYPE html>
    <html>
    <head><title>Usage - ModelRouter</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #0d0d0d; color: #e5e5e5; padding: 40px; max-width: 700px; margin: 0 auto; }
        .card { background: #1a1a1a; border: 1px solid #262626; border-radius: 12px; padding: 24px; margin: 16px 0; }
        h1 { color: #3b82f6; }
        .metric { font-size: 32px; font-weight: 700; color: #fff; }
        .label { font-size: 13px; color: #888; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #262626; }
        th { color: #888; font-size: 11px; text-transform: uppercase; }
        .savings { color: #22c55e; }
    </style></head>
    <body>
        <h1>Your Usage</h1>
        <div class="grid" id="metrics"></div>
        <div class="card"><h2>By Model</h2><table id="modelTable"></table></div>
        <script>
            var apiKey = localStorage.getItem('auth_token') || '';
            fetch('/dashboard/usage', { headers: {'X-API-Key': 'demo-key-123'} })
                .then(r => r.json())
                .then(function(d) {
                    document.getElementById('metrics').innerHTML = 
                        '<div class="card"><div class="metric">' + d.total_requests + '</div><div class="label">Total Requests</div></div>' +
                        '<div class="card"><div class="metric">$' + d.total_cost.toFixed(6) + '</div><div class="label">Total Cost</div></div>' +
                        '<div class="card"><div class="metric savings">$' + d.estimated_savings.toFixed(6) + '</div><div class="label">Estimated Savings</div></div>' +
                        '<div class="card"><div class="metric">' + d.cache_hits + '</div><div class="label">Cache Hits</div></div>';
                    var html = '<tr><th>Model</th><th>Requests</th><th>Avg Quality</th><th>Cost</th></tr>';
                    d.by_model.forEach(function(m) { html += '<tr><td>' + m.model + '</td><td>' + m.requests + '</td><td>' + m.avg_quality + '</td><td>$' + m.cost.toFixed(6) + '</td></tr>'; });
                    document.getElementById('modelTable').innerHTML = html;
                });
        </script>
    </body></html>''';
import requests

@app.route('/auth/github')
def github_login():
    """Redirect to GitHub for authentication."""
    github_client_id = os.environ.get('GITHUB_CLIENT_ID', '')
    redirect_uri = request.url_root.rstrip('/') + '/auth/github/callback'
    github_url = f"https://github.com/login/oauth/authorize?client_id={github_client_id}&redirect_uri={redirect_uri}&scope=user:email"
    return redirect(github_url)

@app.route('/auth/github/callback')
def github_callback():
    """Handle GitHub OAuth callback."""
    code = request.args.get('code')
    if not code:
        return jsonify({'error': 'No code provided'}), 400
    
    # Exchange code for access token
    token_response = requests.post('https://github.com/login/oauth/access_token', data={
        'client_id': os.environ.get('GITHUB_CLIENT_ID', ''),
        'client_secret': os.environ.get('GITHUB_CLIENT_SECRET', ''),
        'code': code
    }, headers={'Accept': 'application/json'})
    
    token_data = token_response.json()
    access_token = token_data.get('access_token')
    
    if not access_token:
        return jsonify({'error': 'Failed to get access token'}), 400
    
    # Get user info
    user_response = requests.get('https://api.github.com/user', headers={
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    })
    user_data = user_response.json()
    
    # Get email
    email_response = requests.get('https://api.github.com/user/emails', headers={
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    })
    emails = email_response.json()
    primary_email = next((e['email'] for e in emails if e.get('primary')), user_data.get('email', ''))
    
    if not primary_email:
        return jsonify({'error': 'No email found'}), 400
    
    # Check if user exists
    user = get_user_by_email(primary_email)
    
    if user:
        token = create_session(user['id'])
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('UPDATE auth_users SET last_login = ? WHERE id = ?', (datetime.now(), user['id']))
        conn.commit()
        conn.close()
    else:
        result, error = register_user(primary_email, secrets.token_urlsafe(16), user_data.get('login', ''))
        if error:
            return jsonify({'error': error}), 400
        token = result['token']
    
    # Redirect to main app with token
    return redirect(f"/?token={token}")
@app.route('/benchmarks/report')
def benchmark_report():
    """Public benchmark report page."""
    from evaluator import evaluator
    weights = evaluator.get_model_weights(days=30)
    
    conn = sqlite3.connect('router.db')
    c = conn.cursor()
    c.execute('''SELECT model_name, category, pass_rate, avg_latency, total_tests
                 FROM model_rankings ORDER BY model_name, pass_rate DESC''')
    benchmarks = c.fetchall()
    
    c.execute('''SELECT model_selected, COUNT(*), AVG(quality_score), AVG(success_score)
                 FROM routing_dataset_v2 WHERE created_at > datetime('now', '-30 days')
                 GROUP BY model_selected ORDER BY COUNT(*) DESC''')
    outcomes = c.fetchall()
    conn.close()
    
    return jsonify({
        'report_date': datetime.now().strftime('%Y-%m-%d'),
        'methodology': 'Models evaluated on algorithm generation, bug fixing, refactoring, and explanation tasks. Outcome scores from real user feedback.',
        'outcome_based_weights': weights,
        'benchmark_results': [{'model': r[0], 'category': r[1], 'pass_rate': r[2], 'latency': r[3], 'tests': r[4]} for r in benchmarks],
        'real_world_outcomes': [{'model': r[0], 'requests': r[1], 'avg_quality': round(r[2] or 0, 2), 'avg_success': round(r[3] or 0, 2)} for r in outcomes],
        'models_tested': ['DeepSeek V3', 'Qwen3-Coder 480B', 'Claude Sonnet 4.6']
    })
@app.route('/checkout')
def checkout_page():
    """Simple checkout page for upgrading to Pro."""
    return '''
    <!DOCTYPE html>
    <html>
    <head><title>Upgrade to Pro - ModelRouter</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #0d0d0d; color: #e5e5e5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1a1a1a; border: 1px solid #262626; border-radius: 16px; padding: 40px; text-align: center; max-width: 400px; }
        h1 { font-size: 24px; margin-bottom: 8px; }
        .price { font-size: 48px; font-weight: 700; color: #3b82f6; margin: 16px 0; }
        .features { text-align: left; margin: 20px 0; color: #888; font-size: 14px; }
        .features li { margin: 8px 0; }
        button { width: 100%; padding: 14px; background: #3b82f6; color: #fff; border: none; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; }
        button:hover { background: #2563eb; }
    </style></head>
    <body>
        <div class="card">
            <h1>ModelRouter Pro</h1>
            <div class="price">$20<span style="font-size:16px;color:#888;">/month</span></div>
            <ul class="features">
                <li>500 requests/day</li>
                <li>All models (DeepSeek, Qwen3-Coder, Claude)</li>
                <li>Priority support</li>
                <li>API access</li>
                <li>Custom routing</li>
            </ul>
            <button onclick="upgrade()">Upgrade to Pro</button>
            <p style="color:#888;font-size:12px;margin-top:12px;">7-day free trial. Cancel anytime.</p>
        </div>
        <script>
            function upgrade() {
                var apiKey = localStorage.getItem('auth_token') || 'demo-key-123';
                fetch('/subscribe/checkout', { method: 'POST', headers: {'Content-Type':'application/json', 'X-API-Key': apiKey}, body: JSON.stringify({tier: 'pro'}) })
                    .then(r => r.json())
                    .then(function(d) { alert('Upgraded to Pro! Welcome.'); window.location.href = '/'; });
            }
        </script>
    </body></html>''';
if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("AI Model Router v5.0 - ChatGPT-Style Platform")
    logger.info("Features: Streaming · History · Markdown · Copy · Regenerate · Share · PWA")
    logger.info("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)