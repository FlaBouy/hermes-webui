#!/usr/bin/env python3
"""Repair the live PA decision graph and make travel/calendar evidence semantic.

This is a source migration for the canonical n8n workflow.  It deliberately
changes the workflow contract, rather than adding phrase-specific handling in
the Biggy UI adapter.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"


AGENT_PROMPT = r"""={{ 'You are Jarvis II, the governed PA decision coordinator. Plan the handoff only; downstream governed nodes execute tools and verify evidence. Return one JSON object and no prose with exactly these keys: intent, required_tools, origin, destination, evidence_required, memory_action, requires_approval, spoken_summary, calendar_window. Understand natural phrasing instead of copying sentence tails. For travel, destination is only the physical place the owner means: exclude dates, relative times such as next weekend, calendar clauses, weather clauses, and other requested actions. Default origin to Lynn Haven, Florida unless the owner supplies another origin. For calendar requests, calendar_window must contain time_min and time_max as ISO-8601 UTC values plus expression; resolve relative time from current UTC '+new Date().toISOString()+'. A weekend window spans Saturday 00:00 through Monday 00:00. required_tools may use only rag_core, maps, lodging_poi, calendar_read, weather, gmail_read, research. For travel include maps and lodging_poi; for calendar include calendar_read. A named venue, plant, attraction, or ordinary address is valid without city/state and must be verified downstream. Conversation memory can recover a follow-up target but is not evidence. Durable memory writes are forbidden. Conversation context: '+JSON.stringify($('Validate PA Request').first().json.conversationContext||[])+'. Durable strategy context: '+JSON.stringify($json.body?.context?.strategy||{})+'. Owner request: '+$('Validate PA Request').first().json.objective }}"""


NORMALIZE_AGENT = r"""const raw=String($json.output||$json.text||$json.response||'').trim();
let text=raw.replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'').trim();
const first=text.indexOf('{'); const last=text.lastIndexOf('}');
if(first>=0&&last>first) text=text.slice(first,last+1);
let plan={}; try{plan=JSON.parse(text)}catch(e){}
const allowed=['rag_core','maps','lodging_poi','calendar_read','weather','gmail_read','research'];
const required=Array.isArray(plan.required_tools)?plan.required_tools.map(String).filter(x=>allowed.includes(x)):[];
const window=plan.calendar_window&&typeof plan.calendar_window==='object'?plan.calendar_window:null;
const valid=Boolean(String(plan.intent||'').trim())&&Array.isArray(plan.required_tools);
if(!valid){return [{json:{plannerPath:'agentic_120b',body:{choices:[{message:{content:JSON.stringify({intent:'ambiguous',required_tools:[],origin:'',destination:'',evidence_required:true,memory_action:'read_none',requires_approval:false,spoken_summary:'I could not form a governed plan for that request.',calendar_window:null})}}]},agentPlanValid:false}}];}
plan={...plan,required_tools:required,calendar_window:window,memory_action:'read_none',requires_approval:false};
return [{json:{plannerPath:'agentic_120b',body:{choices:[{message:{content:JSON.stringify(plan)}}]},agentPlanValid:true}}];"""


VALIDATE_DESTINATION = r"""const response=$json||{}; const body=response.body||{};
const base=$('Merge Calendar Evidence').first().json;
const query=String(base.destinationQuery||base.destination||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,' ');
const label=String(body.destination?.label||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,' ');
const stop=new Set(('a an the to from map mapped route routed drive driving directions me us my our please hey biggy argus jarvis ask have having how about get getting go going check checking calendar schedule conflict conflicts availability on at in for and while of this that next current coming today tomorrow tonight weekend week weekday morning afternoon evening january february march april may june july august september october november december monday tuesday wednesday thursday friday saturday sunday st nd rd th').split(/\s+/));
const aliases={fl:'florida',ga:'georgia',al:'alabama',tn:'tennessee'};
const tokens=value=>value.toLowerCase().replace(/([a-z])[-']([a-z])/g,'$1 $2').replace(/\b\d{1,4}(?:st|nd|rd|th)?\b/g,' ').replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/).map(x=>aliases[x]||x).filter(x=>x.length>=3&&!stop.has(x));
const requested=[...new Set(tokens(query))]; const resolved=new Set(tokens(label));
const overlap=requested.filter(token=>resolved.has(token));
const ratio=requested.length?overlap.length/requested.length:0;
const accepted=Boolean(body.ok===true&&label&&requested.length&&((requested.length===1&&overlap.length===1)||(requested.length>1&&ratio>=0.67)));
return [{json:{...response,destinationMatch:{schema:'jarvis.destination_match.v1',accepted,query,label,requested_tokens:requested,matched_tokens:overlap,ratio:Number(ratio.toFixed(3)),reason:accepted?null:'SEMANTIC_DESTINATION_MISMATCH'}}}];"""


CALENDAR_WINDOW = r"""const base=$json; const objective=String(base.routingObjective||base.destinationQuery||base.destination||'');
const supplied=base.calendarWindow&&typeof base.calendarWindow==='object'?base.calendarWindow:null;
const validIso=value=>{const time=Date.parse(String(value||'')); return Number.isFinite(time)?new Date(time):null;};
let start=supplied?validIso(supplied.time_min):null; let end=supplied?validIso(supplied.time_max):null; let expression=String(supplied?.expression||'').trim();
const day=24*60*60*1000; const utcDay=value=>new Date(Date.UTC(value.getUTCFullYear(),value.getUTCMonth(),value.getUTCDate()));
const now=new Date(); const today=utcDay(now); const lower=objective.toLowerCase();
const nextWeekday=(weekday,strict)=>{const delta=(weekday-today.getUTCDay()+7)%7; return new Date(today.getTime()+((delta===0&&strict?7:delta)*day));};
if(!start||!end||end<=start){start=null; end=null;
 const iso=objective.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);
 const month=objective.match(/\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?/i);
 if(iso){start=new Date(Date.UTC(Number(iso[1]),Number(iso[2])-1,Number(iso[3]))); end=new Date(start.getTime()+day); expression=iso[0];}
 else if(month){const names=['january','february','march','april','may','june','july','august','september','october','november','december']; let year=Number(month[3]||today.getUTCFullYear()); start=new Date(Date.UTC(year,names.indexOf(month[1].toLowerCase()),Number(month[2]))); if(!month[3]&&start<today)start=new Date(Date.UTC(year+1,names.indexOf(month[1].toLowerCase()),Number(month[2]))); end=new Date(start.getTime()+day); expression=month[0];}
 else if(/\bnext\s+weekend\b/.test(lower)){start=nextWeekday(6,true); end=new Date(start.getTime()+2*day); expression='next weekend';}
 else if(/\bthis\s+weekend\b/.test(lower)){start=nextWeekday(6,false); end=new Date(start.getTime()+2*day); expression='this weekend';}
 else if(/\bnext\s+week\b/.test(lower)){start=nextWeekday(1,true); end=new Date(start.getTime()+7*day); expression='next week';}
 else if(/\btomorrow\b/.test(lower)){start=new Date(today.getTime()+day); end=new Date(start.getTime()+day); expression='tomorrow';}
 else {const weekdays=['sunday','monday','tuesday','wednesday','thursday','friday','saturday']; const found=weekdays.findIndex(name=>new RegExp('\\b(?:next\\s+)?'+name+'\\b').test(lower)); if(found>=0){const strict=new RegExp('\\bnext\\s+'+weekdays[found]+'\\b').test(lower); start=nextWeekday(found,strict); end=new Date(start.getTime()+day); expression=(strict?'next ':'')+weekdays[found];}}
}
if(!start||!end){start=today; end=new Date(start.getTime()+day); expression=expression||'today';}
return [{json:{...base,calendarWindow:{time_min:start.toISOString(),time_max:end.toISOString(),expression},time_min:start.toISOString(),time_max:end.toISOString(),max_results:10}}];"""


def main() -> None:
    raw = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    workflow = raw[0] if isinstance(raw, list) else raw
    nodes = {node["name"]: node for node in workflow["nodes"]}

    nodes["Jarvis II Decision Agent"]["parameters"]["text"] = AGENT_PROMPT
    nodes["Prepare Calendar Window"]["parameters"]["jsCode"] = CALENDAR_WINDOW

    governed = nodes["Governed PA Response"]["parameters"]["jsCode"]
    if "const calendarWindow=" not in governed:
        governed = governed.replace(
            "const rawTools=Array.isArray(plan.required_tools)?plan.required_tools:[];",
            "const calendarWindow=plan.calendar_window&&typeof plan.calendar_window==='object'?plan.calendar_window:null; const rawTools=Array.isArray(plan.required_tools)?plan.required_tools:[];",
        ).replace(
            "weatherLocation,radarRequested,destinationResearchRequired",
            "weatherLocation,radarRequested,calendarWindow,destinationResearchRequired",
        )
    nodes["Governed PA Response"]["parameters"]["jsCode"] = governed

    nodes["Normalize Agent Decision"] = {
        "parameters": {"jsCode": NORMALIZE_AGENT},
        "id": "pa_agent_normalize_v2",
        "name": "Normalize Agent Decision",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1120, 240],
    }
    nodes["Validate Named Destination"] = {
        "parameters": {"jsCode": VALIDATE_DESTINATION},
        "id": "pa_destination_semantic_gate_v2",
        "name": "Validate Named Destination",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [3120, -16],
    }

    condition = nodes["Named Destination Resolved?"]["parameters"]["conditions"]["conditions"][0]
    condition["leftValue"] = "={{ ($json.destinationMatch && $json.destinationMatch.accepted === true) ? 'RESOLVED' : 'NOT_RESOLVED' }}"

    assemble = nodes["Assemble Named Destination"]["parameters"]["jsCode"]
    assemble = assemble.replace(
        "destinationEvidence:ok?{provider:'mapbox_geocoding_v6',query:evidence.query,place}:null",
        "destinationEvidence:ok?{provider:'mapbox_geocoding_v6',query:evidence.query,place,contract:$json.destinationMatch||null}:null",
    )
    nodes["Assemble Named Destination"]["parameters"]["jsCode"] = assemble

    render = nodes["Render Travel Evidence"]["parameters"]["jsCode"]
    if "authority:'n8n_pa_core'" not in render:
        render = render.replace(
            "map_view_model:mapView,recommendation_view_model:lodging",
            "map_view_model:mapView,route_contract:{schema:'argus.route_acceptance.v2',status:ready?'VERIFIED':'REJECTED',authority:'n8n_pa_core',destination_query:String(base.destinationQuery||''),resolved_destination:ready?String(destination||''):'',calendar_window:base.calendarWindow||null},recommendation_view_model:lodging",
        )
    nodes["Render Travel Evidence"]["parameters"]["jsCode"] = render

    workflow["nodes"] = list(nodes.values())
    connections = workflow["connections"]
    connections["Deterministic Plan?"]["main"][1] = [{"node": "Jarvis II Decision Agent", "type": "main", "index": 0}]
    connections["Jarvis II Decision Agent"] = {"main": [[{"node": "Normalize Agent Decision", "type": "main", "index": 0}]]}
    connections["Normalize Agent Decision"] = {"main": [[{"node": "Governed PA Response", "type": "main", "index": 0}]]}
    connections["Resolve Named Destination"] = {"main": [[{"node": "Validate Named Destination", "type": "main", "index": 0}]]}
    connections["Validate Named Destination"] = {"main": [[{"node": "Named Destination Resolved?", "type": "main", "index": 0}]]}

    WORKFLOW.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
