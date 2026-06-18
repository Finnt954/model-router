"""
ModelRouter Marketplace
Community-contributed routing strategies and custom models.
"""

import json
import sqlite3
from datetime import datetime

class RoutingMarketplace:
    """
    Let developers publish custom routing strategies.
    Platform takes 15-30% of revenue from paid strategies.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS marketplace_strategies
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT, author TEXT, description TEXT,
                      price REAL DEFAULT 0, downloads INTEGER DEFAULT 0,
                      rating REAL DEFAULT 0, config JSON,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS marketplace_installs
                     (user_id TEXT, strategy_id INTEGER,
                      installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (user_id, strategy_id))''')
        conn.commit()
        conn.close()
    
    def publish_strategy(self, name, author, description, config, price=0):
        """Publish a new routing strategy to the marketplace."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO marketplace_strategies (name, author, description, price, config)
                     VALUES (?, ?, ?, ?, ?)''',
                  (name, author, description, price, json.dumps(config)))
        strategy_id = c.lastrowid
        conn.commit()
        conn.close()
        return strategy_id
    
    def list_strategies(self, sort_by='downloads', limit=50):
        """List available routing strategies."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(f'''SELECT * FROM marketplace_strategies 
                     ORDER BY {sort_by} DESC LIMIT ?''', (limit,))
        rows = c.fetchall()
        conn.close()
        
        return [{
            'id': r[0], 'name': r[1], 'author': r[2],
            'description': r[3], 'price': r[4],
            'downloads': r[5], 'rating': r[6]
        } for r in rows]
    
    def install_strategy(self, user_id, strategy_id):
        """Install a strategy for a user."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO marketplace_installs VALUES (?, ?, ?)',
                  (user_id, strategy_id, datetime.now()))
        c.execute('UPDATE marketplace_strategies SET downloads = downloads + 1 WHERE id = ?',
                  (strategy_id,))
        conn.commit()
        conn.close()
    
    def get_installed_strategies(self, user_id):
        """Get strategies installed by a user."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT s.* FROM marketplace_strategies s
                     JOIN marketplace_installs i ON s.id = i.strategy_id
                     WHERE i.user_id = ?''', (user_id,))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'name': r[1], 'config': json.loads(r[7])} for r in rows]
    
    def apply_strategies(self, user_id, prompt, base_routing):
        """Apply user's installed strategies to modify routing."""
        strategies = self.get_installed_strategies(user_id)
        routing = base_routing
        
        for strategy in strategies:
            config = strategy['config']
            # Apply custom rules from the strategy
            if 'model_override' in config:
                routing = config['model_override']
            if 'task_rules' in config:
                for task, model in config['task_rules'].items():
                    if task in prompt.lower():
                        routing = model
        
        return routing


marketplace = RoutingMarketplace()

# ─── Example: Publish a sample strategy ─────────────────────────

def seed_marketplace():
    """Add some sample strategies to bootstrap the marketplace."""
    strategies = [
        {
            'name': 'Python Specialist',
            'author': 'modelrouter',
            'description': 'Routes all Python tasks to Claude for better type hints and docstrings',
            'price': 0,
            'config': {
                'task_rules': {
                    'python': 'claude',
                    'django': 'claude',
                    'flask': 'claude'
                }
            }
        },
        {
            'name': 'Speed Optimizer',
            'author': 'modelrouter',
            'description': 'Routes everything to DeepSeek for maximum speed and minimum cost',
            'price': 0,
            'config': {
                'model_override': 'deepseek'
            }
        },
        {
            'name': 'Enterprise Guardrails',
            'author': 'modelrouter',
            'description': 'Never routes code to non-enterprise models. Adds compliance checks.',
            'price': 49,
            'config': {
                'allowed_models': ['claude'],
                'audit_every_request': True,
                'max_code_length': 5000
            }
        }
    ]
    
    for s in strategies:
        marketplace.publish_strategy(s['name'], s['author'], s['description'], s['config'], s['price'])
    
    print(f"Seeded {len(strategies)} marketplace strategies")

if __name__ == '__main__':
    seed_marketplace()