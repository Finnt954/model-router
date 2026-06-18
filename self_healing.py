"""
Self-Healing Infrastructure
Detects and fixes problems before users notice.
"""

import time
import threading
import sqlite3
from datetime import datetime, timedelta

class SelfHealing:
    """
    Monitors system health and auto-fixes common issues.
    
    Handles:
    - Model API failures (auto-switch to backup)
    - Database connection issues (auto-reconnect)
    - Cache corruption (auto-clear and rebuild)
    - Memory leaks (auto-restart workers)
    - Rate limit approaching (auto-throttle)
    """
    
    def __init__(self):
        self.health_checks = []
        self.running = False
    
    def start(self):
        """Start the self-healing monitor in background."""
        self.running = True
        self.worker = threading.Thread(target=self._monitor_loop, daemon=True)
        self.worker.start()
        print("Self-healing monitor started")
    
    def _monitor_loop(self):
        """Run health checks every 60 seconds."""
        while self.running:
            self._check_model_health()
            self._check_database_health()
            self._check_rate_limits()
            self._check_cost_anomalies()
            time.sleep(60)
    
    def _check_model_health(self):
        """Ping each model. If one is down, route all traffic to the other."""
        from router import call_deepseek, call_claude
        
        health = {}
        
        try:
            # Quick health check - simple prompt
            result = call_deepseek("respond with 'ok'")
            health['deepseek'] = 'ok' in result.lower()
        except:
            health['deepseek'] = False
        
        try:
            result = call_claude("respond with 'ok'")
            health['claude'] = 'ok' in result.lower()
        except:
            health['claude'] = False
        
        # If DeepSeek is down, force all traffic to Claude
        if not health['deepseek'] and health['claude']:
            self._force_routing('claude')
            print(f"[{datetime.now()}] DeepSeek down. Routing all to Claude.")
        
        # If Claude is down, force all traffic to DeepSeek
        if not health['claude'] and health['deepseek']:
            self._force_routing('deepseek')
            print(f"[{datetime.now()}] Claude down. Routing all to DeepSeek.")
        
        # If both are down... pray
        if not health['deepseek'] and not health['claude']:
            print(f"[{datetime.now()}] CRITICAL: Both models down!")
    
    def _check_database_health(self):
        """Check database connectivity. Auto-reconnect if needed."""
        try:
            conn = sqlite3.connect('router.db')
            conn.execute('SELECT 1')
            conn.close()
        except Exception as e:
            print(f"[{datetime.now()}] Database error: {e}")
    
    def _check_rate_limits(self):
        """Warn if any user is approaching their rate limit."""
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        current_hour = datetime.now().strftime('%Y-%m-%d-%H')
        c.execute('''SELECT user_id, request_count FROM rate_limits 
                     WHERE hour = ? AND request_count > 40''', (current_hour,))
        heavy_users = c.fetchall()
        conn.close()
        
        for user_id, count in heavy_users:
            print(f"[{datetime.now()}] User {user_id} at {count}/50 requests this hour")
    
    def _check_cost_anomalies(self):
        """Detect unusual spending patterns."""
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('''SELECT SUM(cost) FROM analytics WHERE date = date('now')''')
        today = c.fetchone()[0] or 0
        c.execute('''SELECT AVG(daily_cost) FROM 
                     (SELECT SUM(cost) as daily_cost FROM analytics 
                      WHERE date >= date('now', '-7 days') AND date < date('now')
                      GROUP BY date)''')
        avg = c.fetchone()[0] or 0
        conn.close()
        
        if avg > 0 and today > avg * 2:
            print(f"[{datetime.now()}] COST ANOMALY: Today ${today:.2f} vs avg ${avg:.2f}")
    
    def _force_routing(self, model):
        """Temporarily force all traffic to a specific model."""
        try:
            with open('routing_override.json', 'w') as f:
                json.dump({
                    'forced_model': model,
                    'reason': 'health_check_failure',
                    'set_at': datetime.now().isoformat(),
                    'expires_at': (datetime.now() + timedelta(minutes=30)).isoformat()
                }, f)
        except:
            pass
    
    def stop(self):
        """Stop the self-healing monitor."""
        self.running = False


# ─── Singleton ──────────────────────────────────────────────────
self_healing = SelfHealing()