"""
Predictive Pre-Computation Engine
Caches responses to common tasks BEFORE users ask.
Instant responses at zero API cost.
"""

import sqlite3
import hashlib
from datetime import datetime, timedelta
from collections import Counter

class PredictiveCache:
    """
    Predicts what users will ask and pre-computes responses.
    
    Analyzes usage patterns:
    - Peak hours: 9-11am, 2-4pm weekdays
    - Common tasks: "write a binary search", "fix null pointer", etc.
    - Trending tasks: what's being asked more this week vs last week
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
    
    def analyze_trending_tasks(self, days=7):
        """Find the most common tasks users are asking."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT content, COUNT(*) as freq
                     FROM history 
                     WHERE role = 'user'
                     AND created_at > date('now', '-? days')
                     GROUP BY content
                     ORDER BY freq DESC
                     LIMIT 100''', (days,))
        rows = c.fetchall()
        conn.close()
        
        return [{'prompt': r[0], 'frequency': r[1]} for r in rows]
    
    def analyze_peak_hours(self):
        """Find when users are most active."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT strftime('%H', created_at) as hour, COUNT(*) as count
                     FROM history 
                     WHERE role = 'user'
                     AND created_at > date('now', '-30 days')
                     GROUP BY hour
                     ORDER BY count DESC''')
        rows = c.fetchall()
        conn.close()
        
        return [{'hour': f"{r[0]}:00", 'requests': r[1]} for r in rows]
    
    def pre_compute(self, top_n=20):
        """
        Pre-compute responses for the top N trending tasks.
        Runs during off-peak hours (3-5am).
        """
        trending = self.analyze_trending_tasks(days=3)
        top_tasks = trending[:top_n]
        
        pre_computed = []
        for task in top_tasks:
            # Check if already cached
            prompt_hash = hashlib.sha256(task['prompt'].encode()).hexdigest()
            
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT 1 FROM cache WHERE prompt_hash = ?', (prompt_hash,))
            exists = c.fetchone()
            conn.close()
            
            if not exists:
                # Pre-compute this response
                from router import process_with_fallback
                result = process_with_fallback(task['prompt'])
                pre_computed.append({
                    'prompt': task['prompt'][:50],
                    'model': result.get('model_used', 'unknown'),
                    'cost_saved': 'Response now free (cached)'
                })
        
        return {
            'pre_computed': len(pre_computed),
            'tasks': pre_computed,
            'estimated_savings': f"${len(pre_computed) * 0.0003:.4f}/day"
        }
    
    def get_warm_cache_stats(self):
        """Show how effective pre-computation is."""
        total_requests = 0
        cache_hits = 0
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*), SUM(hit_count - 1) FROM cache')
        row = c.fetchone()
        conn.close()
        
        if row:
            total_requests = row[0] or 0
            cache_hits = row[1] or 0
        
        return {
            'cached_responses': total_requests,
            'cache_hits': cache_hits,
            'hit_rate': round(cache_hits / max(total_requests + cache_hits, 1) * 100, 1),
            'cost_saved': f"${cache_hits * 0.0003:.4f}"
        }


# ─── Usage ──────────────────────────────────────────────────────

if __name__ == '__main__':
    predictive = PredictiveCache()
    
    print("Trending tasks:")
    for task in predictive.analyze_trending_tasks(7)[:5]:
        print(f"  ({task['frequency']}x) {task['prompt'][:60]}...")
    
    print("\nPeak hours:")
    for hour in predictive.analyze_peak_hours()[:3]:
        print(f"  {hour['hour']}: {hour['requests']} requests")
    
    print("\nPre-computing top tasks...")
    result = predictive.pre_compute(top_n=10)
    print(f"Pre-computed {result['pre_computed']} responses")
    print(f"Estimated savings: {result['estimated_savings']}")