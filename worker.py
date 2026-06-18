"""
Background Task Worker
Processes expensive API calls without blocking the web server.
This is how production apps handle 100+ simultaneous users.
"""

import time
import json
import sqlite3
from datetime import datetime

# In production, replace this with Celery or RQ
# For now, this demonstrates the architecture

class TaskQueue:
    """
    Simple background task queue.
    In production, replace with Celery + Redis for distributed processing.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS task_queue
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      task_type TEXT,
                      payload TEXT,
                      status TEXT DEFAULT 'pending',
                      result TEXT,
                      created_at TIMESTAMP,
                      completed_at TIMESTAMP)''')
        conn.commit()
        conn.close()
    
    def enqueue(self, task_type, payload):
        """Add a task to the queue. Non-blocking."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO task_queue (task_type, payload, created_at) VALUES (?, ?, ?)',
                  (task_type, json.dumps(payload), datetime.now()))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        return task_id
    
    def dequeue(self):
        """Get the next pending task."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT id, task_type, payload FROM task_queue WHERE status = ? ORDER BY created_at ASC LIMIT 1',
                  ('pending',))
        row = c.fetchone()
        if row:
            c.execute('UPDATE task_queue SET status = ? WHERE id = ?', ('processing', row[0]))
            conn.commit()
        conn.close()
        return row
    
    def complete(self, task_id, result):
        """Mark a task as completed."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE task_queue SET status = ?, result = ?, completed_at = ? WHERE id = ?',
                  ('completed', json.dumps(result), datetime.now(), task_id))
        conn.commit()
        conn.close()
    
    def get_result(self, task_id):
        """Check if a task is done and get the result."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT status, result FROM task_queue WHERE id = ?', (task_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] == 'completed':
            return json.loads(row[1])
        return None


# ─── Singleton ──────────────────────────────────────────────────
task_queue = TaskQueue()


def process_async(prompt, model_override='auto'):
    """
    Non-blocking version of process_with_fallback.
    Returns immediately with a task_id. Client polls for result.
    """
    task_id = task_queue.enqueue('chat', {
        'prompt': prompt,
        'model_override': model_override
    })
    return task_id