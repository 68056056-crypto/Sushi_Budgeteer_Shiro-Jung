"""Short-lived browser-session storage. JSON only; credentials are never serialized."""
from __future__ import annotations
from dataclasses import asdict, fields
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from .state import BudgeteerState

TTL_SECONDS=86400
# Explicit allowlist excludes the provider client, API key, traces and usage logs.
SESSION_FIELDS=('extra_category','order_closed','checkout_step','food_choice','checkout_result',
 'extras_plan','pending_extra_order','pending_confirmation','details_confirmed',
 'pending_allergy_removals','pending_meat_scope','last_options','confirmed_option',
 '_has_recommended','data_mode','allergy_simulation_consent','allergy_simulation_available')

class SessionStore:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv('SUSHI_SESSION_DB',Path(__file__).resolve().parents[1]/'data'/'sessions.sqlite3'))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL)')
    @contextmanager
    def _connect(self):
        connection=sqlite3.connect(self.path,timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    @staticmethod
    def valid_token(token):
        return isinstance(token,str) and re.fullmatch(r'[a-f0-9]{64}',token) is not None
    def save(self,token,agent,history):
        if not self.valid_token(token): raise ValueError('invalid session token')
        payload={'version':1,'configured_mode':agent.configured_data_mode,'state':asdict(agent.state),
                 'agent':{key:getattr(agent,key) for key in SESSION_FIELDS},'history':history[-48:]}
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>2_000_000: raise ValueError('session too large')
        with self._connect() as db:
            db.execute('DELETE FROM sessions WHERE updated < ?',(time.time()-TTL_SECONDS,))
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?)',(token,time.time(),encoded))
    def restore(self,token,agent):
        if not self.valid_token(token): return None
        with self._connect() as db:
            row=db.execute('SELECT updated,payload FROM sessions WHERE token=?',(token,)).fetchone()
        if not row or row[0]<time.time()-TTL_SECONDS: return None
        try:
            payload=json.loads(row[1])
            if payload.get('version')!=1 or payload.get('configured_mode')!=agent.configured_data_mode: return None
            values=payload['state'];allowed={f.name for f in fields(BudgeteerState)}
            state=BudgeteerState(**{key:value for key,value in values.items() if key in allowed})
            saved=payload['agent']
            # Revalidate stored food snapshots against today's catalogue and policy.
            # Never trust an old success flag after a price/catalogue/policy change.
            from .database import records
            from .policy import validate_result
            snapshots=[*saved.get('last_options',[])]
            snapshots.extend(saved[key] for key in ('food_choice','checkout_result') if saved.get(key))
            if state.last_result: snapshots.append(state.last_result)
            invalid=any(not validate_result(result,records(),mode=saved.get('data_mode','strict'))['passed'] for result in snapshots)
            history=payload['history']
            if not isinstance(history,list): return None
            agent.state=state
            for key in SESSION_FIELDS:
                if key in saved: setattr(agent,key,saved[key])
            if invalid:
                agent.clear_choices()
                agent.food_choice=None
                agent.checkout_result=None
                agent.checkout_step=None
                agent.order_closed=False
                agent.details_confirmed=False
                agent.pending_confirmation=False
                history=[*history,{'role':'assistant','content':'ข้อมูลเมนูเปลี่ยนแล้วครับ กรุณายืนยันข้อมูลและจัดชุดใหม่ ผมยังจำงบ การแพ้ และความชอบไว้ให้'}]
            return history
        except (KeyError,TypeError,ValueError,json.JSONDecodeError):
            return None
    def delete(self,token):
        with self._connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?',(token,))
