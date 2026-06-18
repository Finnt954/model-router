"""
Billing Engine
Handles subscriptions, usage tracking, invoicing, and payments via Stripe.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from enum import Enum

# In production, use actual Stripe library: pip install stripe
# import stripe
# stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

class PlanTier(Enum):
    """Subscription tiers with limits and pricing."""
    FREE = {
        'name': 'Free',
        'price_monthly': 0,
        'requests_per_day': 50,
        'models': ['deepseek'],
        'cache_enabled': True,
        'support': 'community',
        'api_access': False,
        'custom_routing': False,
        'analytics': False,
    }
    PRO = {
        'name': 'Pro',
        'price_monthly': 20,
        'requests_per_day': 500,
        'models': ['deepseek', 'claude'],
        'cache_enabled': True,
        'support': 'email',
        'api_access': True,
        'custom_routing': True,
        'analytics': True,
    }
    TEAM = {
        'name': 'Team',
        'price_monthly': 100,
        'requests_per_day': 5000,
        'models': ['deepseek', 'claude'],
        'cache_enabled': True,
        'support': 'priority',
        'api_access': True,
        'custom_routing': True,
        'analytics': True,
        'team_seats': 10,
        'shared_budget': True,
        'admin_dashboard': True,
    }
    ENTERPRISE = {
        'name': 'Enterprise',
        'price_monthly': 500,
        'requests_per_day': float('inf'),
        'models': ['deepseek', 'claude'],
        'cache_enabled': True,
        'support': 'dedicated',
        'api_access': True,
        'custom_routing': True,
        'analytics': True,
        'team_seats': float('inf'),
        'shared_budget': True,
        'admin_dashboard': True,
        'sso': True,
        'audit_logs': True,
        'sla_guarantee': '99.9%',
        'on_premise_option': True,
    }


class BillingManager:
    """
    Full billing lifecycle: subscription, usage tracking, invoicing.
    Production uses Stripe. This shows the architecture.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Subscriptions
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id TEXT PRIMARY KEY,
                      stripe_customer_id TEXT,
                      stripe_subscription_id TEXT,
                      tier TEXT DEFAULT 'free',
                      status TEXT DEFAULT 'active',
                      current_period_start TIMESTAMP,
                      current_period_end TIMESTAMP,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Usage records for billing
        c.execute('''CREATE TABLE IF NOT EXISTS usage_records
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT,
                      date DATE,
                      model_used TEXT,
                      request_count INTEGER DEFAULT 0,
                      token_count INTEGER DEFAULT 0,
                      cost REAL DEFAULT 0,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Invoices
        c.execute('''CREATE TABLE IF NOT EXISTS invoices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT,
                      stripe_invoice_id TEXT,
                      period_start DATE,
                      period_end DATE,
                      amount REAL,
                      status TEXT DEFAULT 'pending',
                      paid_at TIMESTAMP,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # BYOK (Bring Your Own Key) configurations
        c.execute('''CREATE TABLE IF NOT EXISTS byok_configs
                     (user_id TEXT PRIMARY KEY,
                      deepseek_key TEXT,
                      anthropic_key TEXT,
                      markup_percent REAL DEFAULT 50,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        conn.commit()
        conn.close()
    
    # ─── SUBSCRIPTIONS ─────────────────────────────────────────
    
    def create_subscription(self, user_id, tier='free'):
        """Create or upgrade a subscription."""
        plan = PlanTier[tier.upper()].value
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO subscriptions 
                     (user_id, tier, status, current_period_start, current_period_end)
                     VALUES (?, ?, 'active', ?, ?)''',
                  (user_id, tier, datetime.now(), datetime.now() + timedelta(days=30)))
        conn.commit()
        conn.close()
        
        return {
            'user_id': user_id,
            'tier': tier,
            'price': plan['price_monthly'],
            'requests_per_day': plan['requests_per_day'],
            'next_billing': (datetime.now() + timedelta(days=30)).isoformat()
        }
    
    def get_subscription(self, user_id):
        """Get current subscription details."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM subscriptions WHERE user_id = ? AND status = ?', (user_id, 'active'))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return self.create_subscription(user_id, 'free')
        
        return {
            'user_id': row[0],
            'tier': row[3],
            'status': row[4],
            'period_start': row[5],
            'period_end': row[6],
        }
    
    def check_access(self, user_id, feature):
        """Check if user's tier allows a specific feature."""
        sub = self.get_subscription(user_id)
        tier = sub['tier']
        plan = PlanTier[tier.upper()].value
        return plan.get(feature, False)
    
    # ─── USAGE TRACKING ────────────────────────────────────────
    
    def record_usage(self, user_id, model_used, token_count, cost):
        """Record API usage for billing. Called after every request."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO usage_records (user_id, date, model_used, request_count, token_count, cost)
                     VALUES (?, ?, ?, 1, ?, ?)
                     ON CONFLICT (user_id, date, model_used) DO UPDATE SET
                     request_count = request_count + 1,
                     token_count = token_count + ?,
                     cost = cost + ?''',
                  (user_id, today, model_used, token_count, cost, token_count, cost))
        conn.commit()
        conn.close()
    
    def get_usage(self, user_id, days=30):
        """Get usage summary for a user."""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT model_used, SUM(request_count), SUM(token_count), SUM(cost)
                     FROM usage_records
                     WHERE user_id = ? AND date >= ?
                     GROUP BY model_used''', (user_id, since))
        rows = c.fetchall()
        conn.close()
        
        return {
            'period_days': days,
            'total_requests': sum(r[1] for r in rows),
            'total_tokens': sum(r[2] for r in rows),
            'total_cost': round(sum(r[3] for r in rows), 4),
            'by_model': [{'model': r[0], 'requests': r[1], 'tokens': r[2], 'cost': round(r[3], 4)} for r in rows]
        }
    
    # ─── INVOICING ─────────────────────────────────────────────
    
    def generate_invoice(self, user_id):
        """Generate a monthly invoice."""
        sub = self.get_subscription(user_id)
        tier = sub['tier']
        plan = PlanTier[tier.upper()].value
        usage = self.get_usage(user_id, days=30)
        
        base_price = plan['price_monthly']
        usage_cost = usage['total_cost']
        
        # Apply 20% margin on API costs
        margin = usage_cost * 0.20
        total = base_price + usage_cost + margin
        
        invoice = {
            'user_id': user_id,
            'tier': tier,
            'period': f"{sub['period_start']} to {sub['period_end']}",
            'base_price': base_price,
            'api_usage': round(usage_cost, 4),
            'platform_fee': round(margin, 4),
            'total_due': round(total, 2),
            'usage_details': usage
        }
        
        # Store invoice
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO invoices (user_id, period_start, period_end, amount, status)
                     VALUES (?, ?, ?, ?, 'pending')''',
                  (user_id, sub['period_start'], sub['period_end'], total))
        conn.commit()
        conn.close()
        
        return invoice
    
    # ─── BYOK (BRING YOUR OWN KEY) ─────────────────────────────
    
    def setup_byok(self, user_id, deepseek_key=None, anthropic_key=None, markup=50):
        """
        User brings their own API keys. We charge a platform fee.
        Margin: 100% (no API costs for us, pure profit).
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO byok_configs VALUES (?, ?, ?, ?, ?)''',
                  (user_id, deepseek_key, anthropic_key, markup, datetime.now()))
        conn.commit()
        conn.close()
        
        return {
            'mode': 'byok',
            'markup': f'{markup}%',
            'benefit': 'You pay API costs directly. We charge a platform fee.'
        }
    
    # ─── PRICING PAGE DATA ─────────────────────────────────────
    
    def get_pricing_page(self):
        """Generate pricing page data for the frontend."""
        plans = []
        for tier in PlanTier:
            plan = tier.value
            plans.append({
                'name': plan['name'],
                'price': plan['price_monthly'],
                'requests': f"{plan['requests_per_day']:,}/day" if plan['requests_per_day'] != float('inf') else 'Unlimited',
                'models': plan['models'],
                'features': [k for k, v in plan.items() if v is True],
                'cta': 'Start Free' if plan['price_monthly'] == 0 else 'Subscribe'
            })
        return plans
    
    # ─── REVENUE ANALYTICS ─────────────────────────────────────
    
    def get_mrr(self):
        """Calculate Monthly Recurring Revenue."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT tier, COUNT(*) as count FROM subscriptions 
                     WHERE status = 'active' GROUP BY tier''')
        rows = c.fetchall()
        conn.close()
        
        mrr = 0
        breakdown = {}
        for tier, count in rows:
            price = PlanTier[tier.upper()].value['price_monthly']
            revenue = price * count
            mrr += revenue
            breakdown[tier] = {'users': count, 'revenue': revenue}
        
        return {
            'mrr': mrr,
            'arr': mrr * 12,
            'breakdown': breakdown,
            'calculated_at': datetime.now().isoformat()
        }


# ─── Singleton ──────────────────────────────────────────────────
billing = BillingManager()