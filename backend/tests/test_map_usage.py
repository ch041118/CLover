import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from app.config import Settings
from app.map_usage import MapUsage

@pytest.fixture
def usage(tmp_path):
    key=Fernet.generate_key()
    settings=Settings(_env_file=None,jwt_secret='x'*48,data_key=key.decode(),maps_usage_path=str(tmp_path/'maps.sqlite3'),maps_cache_allowed=True)
    usage=MapUsage(settings,Fernet(key));usage.clock=lambda:1000000
    return usage


def test_persistent_encrypted_cache_and_direction(usage):
    calls=[]
    def fetch():calls.append(1);return {'address':'서울 테스트로 10'}
    params={'start':'127,37','goal':'128,38'}
    assert usage.run('/driving',params,fetch)==usage.run('/driving',params,fetch)
    second=MapUsage(usage.settings,usage.cipher);second.clock=usage.clock
    second.run('/driving',params,fetch)
    assert len(calls)==1
    second.run('/driving',{'start':'128,38','goal':'127,37'},fetch)
    assert len(calls)==2
    with sqlite3.connect(usage.settings.maps_usage_path) as db:
        rows=str(db.execute('SELECT * FROM cache').fetchall())
        assert '서울' not in rows and '127,37' not in rows
    assert usage.stats()['rows'][0]['reused']==2


def test_expiry_and_changed_ttl_do_not_use_stale_values(usage):
    calls=[]
    def fetch():calls.append(1);return len(calls)
    usage.run('/driving',{},fetch)
    usage.clock=lambda:1000300
    assert usage.run('/driving',{},fetch)==2
    usage.settings.maps_route_cache_seconds=0
    assert usage.run('/driving',{},fetch)==3


def test_failures_not_cached_and_budget_survives_restart(usage):
    usage.settings.maps_daily_call_limit=2
    def fail():raise HTTPException(409,'provider failure')
    for _ in range(2):
        with pytest.raises(HTTPException):usage.run('/geocode',{},fail)
    second=MapUsage(usage.settings,usage.cipher);second.clock=usage.clock
    with pytest.raises(HTTPException,match='호출 한도'):second.run('/geocode',{},lambda:pytest.fail('must not call'))
    second.clock=lambda:1000000+86400
    assert second.run('/geocode',{},lambda:[])==[]


def test_disabled_cache_purges_and_never_reuses(usage):
    usage.run('/geocode',{},lambda:['old'])
    usage.settings.maps_cache_allowed=False
    assert usage.run('/geocode',{},lambda:['new'])==['new']
    assert usage.run('/geocode',{},lambda:['newer'])==['newer']
    with sqlite3.connect(usage.settings.maps_usage_path) as db:
        assert db.execute('SELECT COUNT(*) FROM cache').fetchone()[0]==0


def test_concurrent_repeated_requests_share_result(usage):
    calls=[]
    def fetch():calls.append(1);return ['result']
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:usage.run('/geocode',{},fetch),range(5)))
    assert results==[['result']]*5 and len(calls)==1
