"""
Redis Cache Service
Production caching with automatic fallback to in-memory.
"""

import os
import json
import hashlib
import redis
from datetime import timedelta

class CacheService:
    """
    Multi-layer cache with Redis primary and in-memory fallback.
    Handles Redis failures gracefully.
    """
    
    def __init__(self, redis_url=None, ttl_hours=24):
        self.ttl = timedelta(hours=ttl_hours)
        self.redis_url = redis_url or os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        self.redis = None
        self._fallback = {}
        self._stats = {'hits': 0, 'misses': 0, 'errors': 0}
        
        try:
            self.redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            print(f"Redis connected: {self.redis_url}")
        except Exception as e:
            print(f"Redis unavailable ({e}). Using in-memory cache.")
    
    def _hash(self, key):
        return hashlib.sha256(key.encode()).hexdigest()
    
    def get(self, prompt):
        """Get cached response. Returns dict or None."""
        key = self._hash(prompt)
        
        if self.redis:
            try:
                data = self.redis.get(key)
                if data:
                    self.redis.expire(key, self.ttl)
                    self._stats['hits'] += 1
                    return json.loads(data)
            except Exception as e:
                self._stats['errors'] += 1
                print(f"Redis get error: {e}")
        
        # Fallback
        data = self._fallback.get(key)
        if data:
            self._stats['hits'] += 1
            return data
        
        self._stats['misses'] += 1
        return None
    
    def set(self, prompt, data):
        """Cache a response."""
        key = self._hash(prompt)
        
        if self.redis:
            try:
                self.redis.setex(key, self.ttl, json.dumps(data))
                return
            except Exception as e:
                self._stats['errors'] += 1
                print(f"Redis set error: {e}")
        
        self._fallback[key] = data
    
    def stats(self):
        """Cache performance metrics."""
        total = self._stats['hits'] + self._stats['misses']
        hit_rate = (self._stats['hits'] / total * 100) if total > 0 else 0
        return {
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'errors': self._stats['errors'],
            'hit_rate': round(hit_rate, 1),
            'backend': 'redis' if self.redis else 'memory'
        }
    
    def clear(self):
        """Clear all cached data."""
        if self.redis:
            try:
                self.redis.flushdb()
            except:
                pass
        self._fallback.clear()


# Singleton
cache = CacheService()