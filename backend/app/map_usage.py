"""Local encrypted optional result cache and persistent API attempt accounting."""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import HTTPException


class MapUsage:
    def __init__(self, settings, cipher):
        self.settings = settings
        self.cipher = cipher
        self.lock = threading.Lock()
        self.clock = time.time

    def connect(self):
        path = Path(self.settings.maps_usage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=5)
        try:
            os.chmod(path, 0o600)
            con.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, kind TEXT, calls INTEGER NOT NULL DEFAULT 0, hits INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day,kind))')
            return con
        except Exception:
            con.close()
            raise

    def day(self):
        return datetime.fromtimestamp(self.clock(), timezone(timedelta(hours=9))).date().isoformat()

    def run(self, path, params, fetch):
        kind = 'address' if 'geocode' in path else 'driving'
        ttl = self.settings.maps_address_cache_seconds if kind == 'address' else self.settings.maps_route_cache_seconds
        identity = json.dumps([path, params, self.settings.naver_maps_key_id.get_secret_value(), self.settings.naver_maps_key.get_secret_value()], sort_keys=True, ensure_ascii=False)
        key = hmac.new(self.settings.data_key.encode(), identity.encode(), hashlib.sha256).hexdigest()
        if not self.lock.acquire(timeout=4):
            raise HTTPException(409, '지도 요청이 처리 중입니다. 잠시 후 다시 시도하세요.')
        con = None
        try:
            con = self.connect()
            now = self.clock(); day = self.day()
            con.execute('BEGIN IMMEDIATE')
            con.execute('DELETE FROM cache WHERE expires <= ?', (now,))
            cutoff = (datetime.fromtimestamp(now, timezone.utc)-timedelta(days=31)).date().isoformat()
            con.execute('DELETE FROM usage WHERE day < ?', (cutoff,))
            if not self.settings.maps_cache_allowed:
                con.execute('DELETE FROM cache')
            else:
                row = con.execute('SELECT value, created FROM cache WHERE key=?', (key,)).fetchone()
                if row and 0 <= now-row[1] < ttl:
                    try:
                        value = json.loads(self.cipher.decrypt(row[0].encode()))
                    except Exception:
                        con.execute('DELETE FROM cache WHERE key=?', (key,))
                    else:
                        con.execute('INSERT INTO usage(day,kind,hits) VALUES(?,?,1) ON CONFLICT(day,kind) DO UPDATE SET hits=hits+1', (day,kind))
                        con.commit()
                        return value
            calls = con.execute('SELECT COALESCE(SUM(calls),0) FROM usage WHERE day=?', (day,)).fetchone()[0]
            if calls >= self.settings.maps_daily_call_limit:
                con.commit()
                raise HTTPException(429, '오늘 지도 API 호출 한도에 도달했습니다. 담당자에게 확인해 주세요.')
            # Reserve before sending: failed requests also consume the local budget.
            con.execute('INSERT INTO usage(day,kind,calls) VALUES(?,?,1) ON CONFLICT(day,kind) DO UPDATE SET calls=calls+1', (day,kind))
            con.commit()
            value = fetch()
            if self.settings.maps_cache_allowed and ttl > 0:
                encoded = self.cipher.encrypt(json.dumps(value,ensure_ascii=False).encode()).decode()
                now = self.clock()
                con.execute('INSERT INTO cache(key,value,created,expires) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,created=excluded.created,expires=excluded.expires', (key,encoded,now,now+ttl))
                con.execute('DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY created DESC LIMIT -1 OFFSET 5000)')
                con.commit()
            return value
        except sqlite3.Error:
            raise HTTPException(409, '지도 사용량 기록을 열 수 없습니다. 서버 저장소를 확인해 주세요.') from None
        finally:
            if con is not None: con.close()
            self.lock.release()

    def stats(self):
        con = self.connect()
        try:
            rows = con.execute('SELECT day,kind,calls,hits FROM usage ORDER BY day DESC,kind LIMIT 64').fetchall()
            return {'today':self.day(),'daily_limit':self.settings.maps_daily_call_limit,
                    'cache_enabled':self.settings.maps_cache_allowed,
                    'rows':[dict(day=d,kind=k,api_attempts=c,reused=h) for d,k,c,h in rows]}
        finally:
            con.close()
