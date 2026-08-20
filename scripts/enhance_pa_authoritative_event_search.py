#!/usr/bin/env python3
"""Add a generic official-host second pass to PA event destination research."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"
OUTPUT = Path("/private/tmp/pa-core-authoritative-event-search.json")


def item(node_id, name, node_type, position, parameters, type_version=2, credentials=None):
    value = {"id": node_id, "name": name, "type": node_type, "typeVersion": type_version, "position": position, "parameters": parameters}
    if credentials:
        value["credentials"] = credentials
    return value


def main() -> None:
    workflow = json.loads(SOURCE.read_text(encoding="utf-8"))[0]
    nodes = {entry["name"]: entry for entry in workflow["nodes"]}
    if "Build Official Destination Search" in nodes:
        raise SystemExit("official-host search already present")

    normalize = nodes["Normalize Destination Sources"]["parameters"]["jsCode"]
    nodes["Normalize Destination Sources"]["parameters"]["jsCode"] = normalize.replace(
        "return [{json:{base:request.base,objective:request.objective,sources}}];",
        "return [{json:{base:request.base,objective:request.objective,query:request.query,sources}}];",
    )

    # Keep each added branch distinct in the n8n canvas.
    for name, position in {
        "Build Destination Extraction": [4848, 96],
        "Extract Destination Candidate": [5088, 96],
        "Validate Destination Claim": [5328, 96],
        "Resolve Researched Destination": [5568, 96],
        "Assemble Researched Destination": [5808, 96],
    }.items():
        nodes[name]["position"] = position

    additions = [
        item(
            "pa_destination_official_build",
            "Build Official Destination Search",
            "n8n-nodes-base.code",
            [4128, -16],
            {"jsCode": """const data=$json; const bad=/(facebook|instagram|tiktok|x\\.com|twitter|reddit|seatgeek|stubhub|ticketmaster|expedia|booking)/i; const official=/(athletic|athletics|tigers|university|college|\\.edu$|\\.gov$|official)/i; const candidates=(data.sources||[]).filter(s=>s&&s.source_host&&!bad.test(s.source_host)).sort((a,b)=>(official.test(b.source_host)?1:0)-(official.test(a.source_host)?1:0)); const host=candidates.find(s=>official.test(s.source_host))?.source_host||''; const query=host ? ('site:'+host+' '+String(data.query||'')) : String(data.query||''); return [{json:{...data,official_host:host,official_query:query}}];"""},
        ),
        item(
            "pa_destination_official_research",
            "Research Official Destination Sources",
            "n8n-nodes-base.httpRequest",
            [4368, -16],
            {"method":"POST","url":"https://api.firecrawl.dev/v2/search","authentication":"genericCredentialType","genericAuthType":"httpHeaderAuth","sendHeaders":True,"headerParameters":{"parameters":[{"name":"Content-Type","value":"application/json"}]},"sendBody":True,"contentType":"json","specifyBody":"json","jsonBody":"={{ JSON.stringify({ query: $json.official_query, limit: 10, sources: ['web'], timeout: 20000, ignoreInvalidURLs: true }) }}","options":{"timeout":30000}},
            type_version=4.2,
            credentials={"httpHeaderAuth":{"id":"ghrdTRdGwcLAv48h","name":"Header Auth account"}},
        ),
        item(
            "pa_destination_official_combine",
            "Combine Authoritative Destination Sources",
            "n8n-nodes-base.code",
            [4608, -16],
            {"jsCode": """const raw=$json||{}; const base=$('Build Official Destination Search').first().json; const groups=[raw.data?.web,raw.data?.results,raw.data,raw.results,raw.web]; const rows=groups.find(Array.isArray)||[]; const bad=/(facebook|instagram|tiktok|x\\.com|twitter|reddit|seatgeek|stubhub|ticketmaster|expedia|booking)/i; const official=/(athletic|athletics|tigers|university|college|\\.edu$|\\.gov$|official)/i; const all=[...(base.sources||[])]; const seen=new Set(all.map(s=>s.url)); for(const row of rows){const url=String(row?.url||row?.metadata?.sourceURL||'').trim(); const m=url.match(/^https?:\\/\\/([^\\/?#]+)/i); const host=m?m[1].toLowerCase():''; if(!host||bad.test(host)||seen.has(url))continue; seen.add(url); all.push({title:String(row?.title||row?.metadata?.title||host).replace(/\\s+/g,' ').trim().slice(0,180),url:url.slice(0,1000),source_host:host.slice(0,180),summary:String(row?.description||row?.metadata?.description||'').replace(/\\s+/g,' ').trim().slice(0,600)});} const score=s=>(official.test(s.source_host)?100:0)+(/schedule|location|stadium|venue|football/i.test(s.title+' '+s.summary)?20:0); all.sort((a,b)=>score(b)-score(a)); return [{json:{base:base.base,objective:base.objective,sources:all.slice(0,8)}}];"""},
        ),
    ]
    workflow["nodes"] = list(nodes.values()) + additions
    connections = workflow["connections"]
    connections["Normalize Destination Sources"] = {"main":[[{"node":"Build Official Destination Search","type":"main","index":0}]]}
    connections["Build Official Destination Search"] = {"main":[[{"node":"Research Official Destination Sources","type":"main","index":0}]]}
    connections["Research Official Destination Sources"] = {"main":[[{"node":"Combine Authoritative Destination Sources","type":"main","index":0}]]}
    connections["Combine Authoritative Destination Sources"] = {"main":[[{"node":"Build Destination Extraction","type":"main","index":0}]]}
    OUTPUT.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")
    SOURCE.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
