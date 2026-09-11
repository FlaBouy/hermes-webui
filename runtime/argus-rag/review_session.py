"""Opt-in active Project Review runtime with isolated remote transport.

The legacy watcher stays available. A marker and dedicated collection prefix are
required for limited validation; production routing cannot be selected here.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
import zipfile

from review_readiness import Registry
from review_watch import ActiveReviewWatcher


class ReviewSession:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['root']).resolve(strict=True)
        self.state = Path(config['state']).resolve()
        self.COLLECTION = config['collection']
        production = config.get('deployment_mode') == 'production'
        if production:
            if self.COLLECTION != 'jarvis_kb' or not config.get('required_mount') or config.get('smb_cache_disabled') is not True:
                raise ValueError('Production requires jarvis_kb, a required mount and cache-disabled SMB')
        elif not re.fullmatch(r'argus_validation_[a-zA-Z0-9_]+', self.COLLECTION):
            raise ValueError('Dedicated argus_validation_ collection required')
        marker = '.argus-production-root' if production else '.argus-validation-root'
        if not (self.root/marker).is_file():
            raise ValueError('Explicit validation root marker required')
        self.state.mkdir(parents=True, exist_ok=True)
        os.environ.update(ARGUS_REVIEW_STATE_DIR=config['registry'], ARGUS_REVIEW_COLLECTION=self.COLLECTION,
                          ARGUS_RAG_LIBRARY_ROOT=config['library_root'])
        self.registry = Registry(config['registry'])
        self.event_lock = threading.Lock()
        self.workers = {}
        self.prewarms = []
        self.stop = threading.Event()
        # Existing local credential store; key never enters configuration or logs.
        with zipfile.ZipFile(config['qdrant_key_docx']) as z:
            text = re.sub(r'<[^>]+>', ' ', z.read('word/document.xml').decode())
        self.key = max(re.findall(r'[A-Za-z0-9_\-]{30,}', text), key=len)
        self.base_url = config['qdrant_url'].rstrip('/')
        try:
            self.qd('/collections/'+self.COLLECTION, method='GET')
        except urllib.error.HTTPError as exc:
            if production or exc.code != 404:
                raise
            self.qd('/collections/'+self.COLLECTION, {'vectors':{'size':768,'distance':'Cosine'}}, method='PUT')
        for lane in ['native','ocr']:
            log = (self.state/('warm-'+lane+'.log')).open('w')
            p = subprocess.Popen([config['extract_python'],str(Path(__file__).with_name('review_extract_worker.py'))],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,
                env={**os.environ,'HF_HUB_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false'})
            self.workers[lane] = (p,threading.Lock(),log)
        self.watcher = ActiveReviewWatcher(self.root,self.state,self.registry,self.COLLECTION,self.ingest_file,self.event)
        self.watcher.required_mount = config.get('required_mount')
        self.watcher.paused = lambda:self.control().get('paused',False)
        for lane, fixture in config.get('prewarm',{}).items():
            t=threading.Thread(target=self.prewarm,args=(lane,fixture),daemon=True)
            t.start();self.prewarms.append(t)
        self.event('session_started',collection=self.COLLECTION,root=str(self.root),pid=os.getpid(),
                   transport=self.base_url,entrypoint='jarvis_rag_projects.py --active',native_slots=1,ocr_slots=1,
                   release=config.get('release'),source_commit=config.get('source_commit'))

    def event(self, kind, **data):
        with self.event_lock, (self.state/'events.jsonl').open('a') as f:
            f.write(json.dumps({'at':time.time(),'kind':kind,**data})+'\n')

    def control(self):
        # Bounded validation fault/priority switches; no production service changes.
        try:return json.loads((self.state/'control.json').read_text())
        except (OSError,ValueError):return {}

    def qd(self, path, body=None, method='POST'):
        prefix='/collections/'+self.COLLECTION
        if path != prefix and not path.startswith(prefix+'/'):
            raise ValueError('Remote collection boundary rejected')
        if self.control().get('qdrant_outage'):
            raise ConnectionError('Controlled validation transport interruption')
        at=time.time()
        req=urllib.request.Request(self.base_url+path,data=json.dumps(body).encode() if body is not None else None,
                                  headers={'Content-Type':'application/json','api-key':self.key},method=method)
        with urllib.request.urlopen(req,timeout=30) as response:result=json.load(response)
        self.event('remote_qdrant',path=path,method=method,seconds=time.time()-at,status=result.get('status'),
                   result_status=result.get('result',{}).get('status') if isinstance(result.get('result'),dict) else None)
        return result

    def embed(self,texts):
        if self.control().get('embedding_outage'):
            raise ConnectionError('Controlled embedding interruption')
        at=time.time()
        req=urllib.request.Request(self.config['embedding_url'],data=json.dumps({'model':'text-embedding-nomic-embed-text-v1.5','input':texts}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=90) as response:result=json.load(response)
        vectors=[r['embedding'] for r in sorted(result['data'],key=lambda x:x['index'])]
        self.event('embeddings',count=len(vectors),seconds=time.time()-at)
        return vectors

    def extract_lane(self,path,state,lane):
        p,lock,_=self.workers[lane]
        with lock:
            if p.poll() is not None:raise RuntimeError('Extraction worker exited')
            p.stdin.write(json.dumps({'path':str(path)})+'\n');p.stdin.flush()
            for line in p.stdout:
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('event')=='state':state(event['state'])
                elif event.get('event')=='error':raise RuntimeError(event['error'])
                elif event.get('event')=='result':return event['text'],event['manifest']
        raise RuntimeError('Extractor stream ended')

    def prewarm(self,lane,path):
        at=time.time()
        try:self.extract_lane(path,lambda value:None,lane);self.event('prewarm_complete',lane=lane,seconds=time.time()-at)
        except Exception as exc:self.event('prewarm_failed',lane=lane,error=str(exc))

    def extract(self,path,state):
        while self.control().get('pause_candidate') and not self.stop.wait(.1):pass
        lane='ocr' if 'review-ocr' in threading.current_thread().name else 'native'
        return self.extract_lane(path,state,lane)

    def ingest_file(self,path,detected_at=None):
        from jarvis_rag_projects import ingest_file
        source=Path(path).resolve().relative_to(Path(self.config['library_root'])).as_posix()
        result=None
        try:
            result=ingest_file(path,root=self.root,engine=self,registry=self.registry,detected_at=detected_at)
            return result
        finally:self.event('terminal',path=str(path),record=result or self.registry.record(self.COLLECTION,source))

    def run(self):
        try:self.watcher.loop()
        except KeyboardInterrupt:pass
        finally:
            self.stop.set()
            for t in self.prewarms:t.join(timeout=30)
            for p,_,log in self.workers.values():
                p.stdin.close()
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=5)
                log.close()
            self.event('session_closed')
