"""
ModelRouter Referral System
Viral growth through "give $10, get $10" referral credits.
"""

import sqlite3
import secrets
from datetime import datetime

class ReferralSystem:
    """
    Referral program: existing users share links.
    New users get free credits. Referrers get credits too.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS referrals
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      referrer_id TEXT,
                      referred_id TEXT,
                      code TEXT UNIQUE,
                      status TEXT DEFAULT 'pending',
                      credit_amount REAL DEFAULT 10.00,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      converted_at TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS referral_codes
                     (user_id TEXT PRIMARY KEY,
                      code TEXT UNIQUE,
                      total_referrals INTEGER DEFAULT 0,
                      total_earned REAL DEFAULT 0,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    
    def create_code(self, user_id):
        """Generate a unique referral code for a user."""
        code = f"REF-{user_id[:6].upper()}-{secrets.token_hex(3).upper()}"
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO referral_codes VALUES (?, ?, 0, 0, ?)',
                  (user_id, code, datetime.now()))
        conn.commit()
        conn.close()
        return code
    
    def get_code(self, user_id):
        """Get or create a referral code."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT code, total_referrals, total_earned FROM referral_codes WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return {'code': row[0], 'referrals': row[1], 'earned': row[2]}
        return {'code': self.create_code(user_id), 'referrals': 0, 'earned': 0}
    
    def apply_referral(self, new_user_id, referral_code):
        """Apply a referral code when a new user signs up."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Find the referrer
        c.execute('SELECT user_id FROM referral_codes WHERE code = ?', (referral_code,))
        row = c.fetchone()
        
        if not row:
            conn.close()
            return False
        
        referrer_id = row[0]
        
        # Create referral record
        c.execute('INSERT INTO referrals (referrer_id, referred_id, code, status) VALUES (?, ?, ?, ?)',
                  (referrer_id, new_user_id, referral_code, 'converted', datetime.now()))
        
        # Update referrer stats
        c.execute('''UPDATE referral_codes 
                     SET total_referrals = total_referrals + 1, total_earned = total_earned + 10 
                     WHERE user_id = ?''', (referrer_id,))
        
        conn.commit()
        conn.close()
        
        # Give new user $10 credit
        return True
    
    def get_referral_stats(self, user_id):
        """Get referral performance for a user."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*), SUM(credit_amount) FROM referrals WHERE referrer_id = ? AND status = ?',
                  (user_id, 'converted'))
        row = c.fetchone()
        conn.close()
        return {'total_referrals': row[0] or 0, 'total_earned': row[1] or 0}


referrals = ReferralSystem()