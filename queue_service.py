"""
Message Queue Service
Handles background tasks without blocking the web server.
In production, replace with Redis Queue (RQ) or Celery.
"""

import threading
import time
import json
from datetime import datetime
from collections import deque

class TaskQueue:
    """
    Background task processor.
    Runs expensive API calls without blocking user requests.
    """
    
    def __init__(self):
        self.queue = deque()
        self.results = {}
        self.worker_thread = None
        self.running = False
    
    def enqueue(self, task_type, payload):
        """Add task to queue. Returns immediately with task_id."""
        task_id = f"task_{int(time.time() * 1000)}"
        self.queue.append({
            'id': task_id,
            'type': task_type,
            'payload': payload,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        })
        self.results[task_id] = {'status': 'pending'}
        
        # Start worker if not running
        if not self.running:
            self.start_worker()
        
        return task_id
    
    def get_result(self, task_id):
        """Check task status and get result."""
        return self.results.get(task_id, {'status': 'not_found'})
    
    def start_worker(self):
        """Start background worker thread."""
        self.running = True
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
    
    def _process_queue(self):
        """Worker loop: processes tasks from the queue."""
        while self.running:
            if self.queue:
                task = self.queue.popleft()
                try:
                    result = self._execute(task)
                    self.results[task['id']] = {
                        'status': 'completed',
                        'result': result,
                        'completed_at': datetime.now().isoformat()
                    }
                except Exception as e:
                    self.results[task['id']] = {
                        'status': 'failed',
                        'error': str(e),
                        'completed_at': datetime.now().isoformat()
                    }
            else:
                time.sleep(0.1)
    
    def _execute(self, task):
        """Execute a task. Override with actual task handlers."""
        if task['type'] == 'chat':
            from router import process_with_fallback
            return process_with_fallback(task['payload']['prompt'])
        elif task['type'] == 'batch_route':
            results = []
            for prompt in task['payload']['prompts']:
                from router import process_with_fallback
                results.append(process_with_fallback(prompt))
            return results
        return None
    
    def stop(self):
        """Stop the worker thread."""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)


# Singleton
task_queue = TaskQueue()