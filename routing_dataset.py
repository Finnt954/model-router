"""
Routing Dataset Collection Engine v2.0
Stores every routing decision with full context for ML training.
This is your proprietary moat — gets more valuable with every request.
"""

import sqlite3
import json
import hashlib
import time
from datetime import datetime, timedelta
from collections import defaultdict

class RoutingDatasetV2:
    """
    Enterprise-grade routing dataset.
    
    Every record captures:
    - Prompt + embedding
    - Task classification + confidence
    - Model chosen + why
    - Latency + cost
    - Response quality score
    - User outcome (success/failure signals)
    - User feedback
    - Conversation context
    - Time of day, day of week
    - User segment (free/pro/enterprise)
    
    This dataset is your competitive advantage.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Main routing dataset
        c.execute('''CREATE TABLE IF NOT EXISTS routing_dataset_v2
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      request_id TEXT UNIQUE,
                      prompt_hash TEXT,
                      prompt_preview TEXT,
                      task_type TEXT,
                      task_confidence REAL,
                      classification_method TEXT,
                      model_selected TEXT,
                      routing_reason TEXT,
                      model_override BOOLEAN DEFAULT 0,
                      latency_ms REAL,
                      cost_microdollars INTEGER,
                      response_length INTEGER,
                      quality_score REAL,
                      success_score REAL,
                      outcome_signals TEXT,
                      user_feedback TEXT,
                      conversation_id TEXT,
                      user_id TEXT,
                      user_tier TEXT DEFAULT 'free',
                      day_of_week INTEGER,
                      hour_of_day INTEGER,
                      context_length INTEGER DEFAULT 0,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Aggregated stats for fast queries
        c.execute('''CREATE TABLE IF NOT EXISTS routing_stats_hourly
                     (hour TIMESTAMP,
                      model TEXT,
                      task_type TEXT,
                      request_count INTEGER DEFAULT 0,
                      avg_latency REAL DEFAULT 0,
                      avg_quality REAL DEFAULT 0,
                      avg_success REAL DEFAULT 0,
                      total_cost REAL DEFAULT 0,
                      PRIMARY KEY (hour, model, task_type))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS routing_stats_daily
                     (date DATE,
                      model TEXT,
                      task_type TEXT,
                      request_count INTEGER DEFAULT 0,
                      avg_latency REAL DEFAULT 0,
                      avg_quality REAL DEFAULT 0,
                      avg_success REAL DEFAULT 0,
                      total_cost REAL DEFAULT 0,
                      cache_hit_rate REAL DEFAULT 0,
                      fallback_rate REAL DEFAULT 0,
                      PRIMARY KEY (date, model, task_type))''')
        
        # Indexes for analytics queries
        c.execute('CREATE INDEX IF NOT EXISTS idx_routing_model ON routing_dataset_v2(model_selected)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_routing_task ON routing_dataset_v2(task_type)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_routing_success ON routing_dataset_v2(success_score)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_routing_user ON routing_dataset_v2(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_routing_created ON routing_dataset_v2(created_at)')
        
        conn.commit()
        conn.close()
    
    def record(self, 
               prompt, 
               task_type, 
               task_confidence,
               classification_method,
               model_selected, 
               routing_reason,
               latency_ms, 
               cost,
               response_length=0,
               user_id='anonymous',
               user_tier='free',
               conversation_id=None,
               model_override=False):
        """Record a single routing decision."""
        request_id = hashlib.sha256(f"{prompt}{time.time()}".encode()).hexdigest()[:16]
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        prompt_preview = prompt[:200]
        cost_microdollars = int(cost * 1_000_000)  # Store as integer for precision
        now = datetime.now()
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO routing_dataset_v2
                     (request_id, prompt_hash, prompt_preview, task_type, task_confidence,
                      classification_method, model_selected, routing_reason, model_override,
                      latency_ms, cost_microdollars, response_length,
                      user_id, user_tier, conversation_id,
                      day_of_week, hour_of_day)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (request_id, prompt_hash, prompt_preview, task_type, task_confidence,
                   classification_method, model_selected, routing_reason, model_override,
                   latency_ms, cost_microdollars, response_length,
                   user_id, user_tier, conversation_id,
                   now.weekday(), now.hour))
        conn.commit()
        conn.close()
        
        return request_id
    
    def update_outcome(self, request_id, quality_score=None, success_score=None, 
                       user_feedback=None, outcome_signals=None):
        """Update a routing record with outcome data."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        updates = []
        params = []
        
        if quality_score is not None:
            updates.append('quality_score = ?')
            params.append(quality_score)
        if success_score is not None:
            updates.append('success_score = ?')
            params.append(success_score)
        if user_feedback is not None:
            updates.append('user_feedback = ?')
            params.append(user_feedback)
        if outcome_signals is not None:
            updates.append('outcome_signals = ?')
            params.append(json.dumps(outcome_signals))
        
        if updates:
            params.append(request_id)
            c.execute(f"UPDATE routing_dataset_v2 SET {', '.join(updates)} WHERE request_id = ?", params)
            conn.commit()
        
        conn.close()
    
    def get_training_data(self, min_success=0.5, limit=50000):
        """Export training data for ML model training."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT prompt_preview, task_type, task_confidence, model_selected,
                     quality_score, success_score, user_feedback, outcome_signals,
                     latency_ms, cost_microdollars, user_tier, day_of_week, hour_of_day
                     FROM routing_dataset_v2
                     WHERE success_score >= ? OR user_feedback = 'up'
                     ORDER BY created_at DESC LIMIT ?''', (min_success, limit))
        rows = c.fetchall()
        conn.close()
        
        return [{
            'prompt': r[0], 'task_type': r[1], 'confidence': r[2], 'model': r[3],
            'quality': r[4], 'success': r[5], 'feedback': r[6], 'signals': r[7],
            'latency': r[8], 'cost': r[9], 'tier': r[10], 'day': r[11], 'hour': r[12]
        } for r in rows]
    
    def get_routing_quality_report(self, days=7):
        """Generate a report on routing quality."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        report = {}
        
        # Overall stats
        c.execute('''SELECT COUNT(*), AVG(quality_score), AVG(success_score), AVG(latency_ms)
                     FROM routing_dataset_v2
                     WHERE created_at > date('now', '-? days')''', (days,))
        row = c.fetchone()
        report['total_requests'] = row[0]
        report['avg_quality'] = round(row[1] or 0, 3)
        report['avg_success'] = round(row[2] or 0, 3)
        report['avg_latency'] = round(row[3] or 0, 1)
        
        # By model
        c.execute('''SELECT model_selected, COUNT(*), AVG(quality_score), AVG(success_score), AVG(latency_ms)
                     FROM routing_dataset_v2
                     WHERE created_at > date('now', '-? days')
                     GROUP BY model_selected''', (days,))
        report['by_model'] = [{
            'model': r[0], 'requests': r[1], 'quality': round(r[2] or 0, 3),
            'success': round(r[3] or 0, 3), 'latency': round(r[4] or 0, 1)
        } for r in c.fetchall()]
        
        # By task type
        c.execute('''SELECT task_type, model_selected, COUNT(*), AVG(success_score)
                     FROM routing_dataset_v2
                     WHERE created_at > date('now', '-? days')
                     GROUP BY task_type, model_selected
                     ORDER BY task_type, AVG(success_score) DESC''', (days,))
        report['by_task'] = [{
            'task': r[0], 'model': r[1], 'requests': r[2], 'success': round(r[3] or 0, 3)
        } for r in c.fetchall()]
        
        # Best model per task type
        report['best_routing'] = {}
        for entry in report['by_task']:
            task = entry['task']
            if task not in report['best_routing'] or entry['success'] > report['best_routing'][task]['success']:
                report['best_routing'][task] = entry
        
        conn.close()
        return report
    
    def get_insights(self):
        """Generate actionable insights from the dataset."""
        report = self.get_routing_quality_report()
        
        insights = []
        
        # Insight 1: Best performing model overall
        if report['by_model']:
            best = max(report['by_model'], key=lambda x: x['success'])
            insights.append(f"{best['model']} has the highest success rate ({best['success']:.1%}) across {best['requests']} requests.")
        
        # Insight 2: Task-specific recommendations
        if report.get('best_routing'):
            for task, entry in report['best_routing'].items():
                insights.append(f"For {task} tasks: {entry['model']} ({entry['success']:.1%} success, {entry['requests']} samples)")
        
        # Insight 3: Quality trends
        if report['avg_quality'] < 0.6:
            insights.append(f"⚠️ Average response quality is low ({report['avg_quality']:.1%}). Consider reviewing routing rules.")
        
        return {
            'report': report,
            'insights': insights,
            'generated_at': datetime.now().isoformat()
        }


# ─── Singleton ──────────────────────────────────────────────────
routing_dataset_v2 = RoutingDatasetV2()