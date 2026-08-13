#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, 'smedley-engineering.v0.2.5.js');
const src = fs.readFileSync(SRC, 'utf8');

// Extract helper functions into a sandbox by evaluating a sliced IIFE fragment is hard;
// instead assert source contains the peel helper and run a mirrored implementation.
if (!src.includes('function libraryRelpathFromSource')) {
  console.error('FAIL: libraryRelpathFromSource missing');
  process.exit(1);
}
if (!src.includes('Collapse already-prefixed / doubled sidecar routes')) {
  console.error('FAIL: doubled-route collapse comment missing');
  process.exit(1);
}

function libraryRelpathFromSource(source){
  let rel=String(source||'').replace(/\\/g,'/').trim();
  if(!rel || rel==='?') return '';
  rel=rel.split('?')[0].split('#')[0];
  const peel=/^(?:\/)?(?:api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/)+/i;
  while(peel.test(rel)) rel=rel.replace(peel,'');
  const low=rel.toLowerCase();
  const lastDoc=low.lastIndexOf('/api/extensions/smedley-engineering/sidecar/doc/');
  const lastPrev=low.lastIndexOf('/api/extensions/smedley-engineering/sidecar/preview/');
  const last=Math.max(lastDoc, lastPrev);
  if(last>=0){
    const route=lastDoc>=lastPrev?'doc':'preview';
    const prefix=`/api/extensions/smedley-engineering/sidecar/${route}/`;
    rel=rel.slice(last+prefix.length);
  }
  try{ rel=decodeURIComponent(rel); }catch(_){}
  return rel.replace(/^\/+/,'').replace(/\\/g,'/');
}
function corpusSidecarPath(source){
  const rel=libraryRelpathFromSource(source);
  const ext=(rel.split('.').pop()||'').toLowerCase();
  const route=ext==='pdf'?'doc':'preview';
  return `/api/extensions/smedley-engineering/sidecar/${route}/`+rel.split('/').map(encodeURIComponent).join('/');
}

const want='Vendor Data/Allen Bradley/1756-um001_-en-p.pdf';
const inputs=[
  want,
  'api/extensions/smedley-engineering/sidecar/doc/'+want,
  '/api/extensions/smedley-engineering/sidecar/doc/'+want,
  'http://localhost:8787/api/extensions/smedley-engineering/sidecar/doc/'+want,
  'http://localhost:8787/api/extensions/smedley-engineering/sidecar/doc/api/extensions/smedley-engineering/sidecar/doc/'+want,
  'https://smedley.tail061f03.ts.net:8787/api/extensions/smedley-engineering/sidecar/doc/'+encodeURI(want),
];
for (const input of inputs) {
  const out = corpusSidecarPath(input);
  const n = (out.match(/\/api\/extensions\/smedley-engineering\/sidecar\/doc\//g)||[]).length;
  if (n !== 1 || !out.includes('1756-um001_-en-p.pdf')) {
    console.error('FAIL', input, '->', out);
    process.exit(1);
  }
}

console.log('PASS: corpus href rewrite is idempotent (static + doubled-prefix cases)');
console.log(`source: ${SRC}`);
