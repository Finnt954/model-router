"""
User-Specific Routing Engine
Learns individual preferences and routes accordingly.
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict, Counter

class UserRouter:
    """
    Learns per-user preferences:
    - User A prefers speed → route to DeepSeek even for refactoring
    - User B prefers detail → route to Claude even for simple tasks
    - User C writes Python all day → optimize for Python-specific models
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS user_preferences
                     (user_id TEXT PRIMARY KEY,
                      preferred_model TEXT,
                      speed_vs_quality REAL DEFAULT 0.5,
                      primary_language TEXT,
                      avg_prompt_length REAL,
                      total_requests INTEGER DEFAULT 0,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_language_stats
                     (user_id TEXT, language TEXT, count INTEGER DEFAULT 1,
                      PRIMARY KEY (user_id, language))''')
        conn.commit()
        conn.close()
    
    def analyze_user(self, user_id):
        """Build a profile of this user's preferences."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Get recent activity
        c.execute('''SELECT model_used, task_type, content, cost, success_score 
                     FROM routing_dataset WHERE user_id = ? 
                     ORDER BY created_at DESC LIMIT 100''', (user_id,))
        rows = c.fetchall()
        
        if not rows:
            conn.close()
            return None
        
        # Preference 1: Speed vs Quality
        deepseek_count = sum(1 for r in rows if 'DeepSeek' in (r[0] or ''))
        claude_count = sum(1 for r in rows if 'Claude' in (r[0] or ''))
        total = deepseek_count + claude_count
        speed_preference = deepseek_count / max(total, 1)
        
        # Preference 2: Primary language
        languages = Counter()
        for r in rows:
            content = r[2] or ''
            for lang in ['python', 'javascript', 'typescript', 'java', 'rust', 'go', 'react', 'sql']:
                if lang in content.lower():
                    languages[lang] += 1
        primary_language = languages.most_common(1)[0][0] if languages else None
        
        # Preference 3: Average prompt complexity
        avg_length = sum(len(r[2] or '') for r in rows) / max(len(rows), 1)
        
        # Preference 4: Success rate per model
        model_success = defaultdict(list)
        for r in rows:
            if r[0] and r[4]:
                model_success[r[0]].append(r[4])
        
        best_model = None
        best_avg = 0
        for model, scores in model_success.items():
            avg = sum(scores) / len(scores)
            if avg > best_avg:
                best_avg = avg
                best_model = model
        
        # Store preferences
        c.execute('''INSERT OR REPLACE INTO user_preferences 
                     (user_id, preferred_model, speed_vs_quality, primary_language, avg_prompt_length, total_requests, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, best_model, round(speed_preference, 2), primary_language, round(avg_length, 0), len(rows), datetime.now()))
        
        if primary_language:
            c.execute('INSERT OR REPLACE INTO user_language_stats (user_id, language, count) VALUES (?, ?, ?)',
                      (user_id, primary_language, languages[primary_language]))
        
        conn.commit()
        conn.close()
        
        return {
            'user_id': user_id,
            'preferred_model': best_model,
            'speed_vs_quality': round(speed_preference, 2),
            'primary_language': primary_language,
            'avg_prompt_length': round(avg_length, 0),
            'total_requests': len(rows),
            'interpretation': 'Prefers speed' if speed_preference > 0.6 else 'Prefers quality' if speed_preference < 0.4 else 'Balanced'
        }
    
    def route_for_user(self, user_id, prompt, default_routing):
        """Override default routing based on user preferences."""
        prefs = self.analyze_user(user_id)
        
        if not prefs:
            return default_routing
        
        routing = default_routing
        
        # If user strongly prefers speed, override refactoring to DeepSeek
        if prefs['speed_vs_quality'] > 0.7:
            routing = 'deepseek'
        
        # If user strongly prefers quality, use Claude more
        if prefs['speed_vs_quality'] < 0.3:
            routing = 'claude'
        
        # If user primarily writes in a specific language, use best model for that
        if prefs['primary_language']:
            if prefs['primary_language'] in ['python', 'javascript', 'typescript']:
                # These languages have great DeepSeek support
                if prefs['speed_vs_quality'] > 0.4:
                    routing = 'deepseek'
        
        return routing


user_router = UserRouter()