#!/usr/bin/env python3
"""Retarget PA destination verification to the proven authenticated Mapbox lane."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"
OUTPUT = Path("/private/tmp/pa-core-destination-resolution.json")


def main() -> None:
    workflow = json.loads(SOURCE.read_text(encoding="utf-8"))[0]
    nodes = {entry["name"]: entry for entry in workflow["nodes"]}
    for name in ("Resolve Named Destination", "Resolve Researched Destination"):
        entry = nodes[name]
        entry["parameters"]["url"] = "http://host.docker.internal:8790/api/jarvis-ii/pa-travel"
        if name == "Resolve Named Destination":
            entry["parameters"]["jsonBody"] = "={{ JSON.stringify({destination:$('Merge Calendar Evidence').first().json.destinationQuery,include_lodging:false}) }}"
        else:
            entry["parameters"]["jsonBody"] = "={{ JSON.stringify({destination:$('Validate Destination Claim').first().json.claim?.query || '',include_lodging:false}) }}"

    nodes["Named Destination Resolved?"]["parameters"]["conditions"]["conditions"][0]["leftValue"] = "={{ ($json.body && $json.body.ok === true && $json.body.destination && $json.body.destination.label) ? 'RESOLVED' : 'NOT_RESOLVED' }}"
    direct_code = nodes["Assemble Named Destination"]["parameters"]["jsCode"]
    nodes["Assemble Named Destination"]["parameters"]["jsCode"] = direct_code.replace("const place=evidence.place||{};", "const place=evidence.destination||{};")
    research_code = nodes["Assemble Researched Destination"]["parameters"]["jsCode"]
    nodes["Assemble Researched Destination"]["parameters"]["jsCode"] = research_code.replace("const place=evidence.place||{};", "const place=evidence.destination||{};")
    governed = nodes["Governed PA Response"]["parameters"]["jsCode"]
    nodes["Governed PA Response"]["parameters"]["jsCode"] = governed.replace(
        "return(c==='x'?r:(r&3|8).toString(16)});",
        "return (c==='x'?r:((r&3)|8)).toString(16)});",
    )
    extraction = nodes["Build Destination Extraction"]["parameters"]["jsCode"]
    nodes["Build Destination Extraction"]["parameters"]["jsCode"] = extraction.replace(
        "Return VERIFIED only when one source supports a concrete venue, plant site, attraction, or addressable place for the owner objective. destination_query must be the exact place name plus city/state when the source supplies them; source_url must exactly match one supplied URL. Otherwise return status NO_VERIFIED_DESTINATION and empty strings. Never invent or use outside knowledge.",
        "Return VERIFIED when one source supports a concrete venue, plant site, attraction, addressable place, or an unambiguous event host locality for the owner objective. If the exact stadium is not named but the host locality is supported, return that locality as a fallback destination; never call the fallback a stadium. destination_query must be a usable Mapbox place query, and source_url must exactly match one supplied URL. Otherwise return status NO_VERIFIED_DESTINATION and empty strings. Do not invent unsupported event facts.",
    )
    # This node receives the resolved branch item.  Reading the original
    # planner item here discarded the verified event destination.
    nodes["Retrieve Travel Evidence"]["parameters"]["jsonBody"] = "={{ JSON.stringify({origin:$json.origin,destination:$json.destination,include_lodging:true}) }}"
    nodes["Build Destination Research"]["parameters"]["jsCode"] = """const base=$('Merge Calendar Evidence').first().json;
const objective=String($('Validate PA Request').first().json.objective||'').replace(/\\s+/g,' ').trim();
const date=objective.match(/\\b(january|february|march|april|may|june|july|august|september|october|november|december)\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s*(\\d{4}))?/i);
const teams=objective.match(/\\b([A-Z][A-Za-z-]{1,40})\\s+(?:vs\\.?|versus)\\s+([A-Z][A-Za-z-]{1,40})\\b/);
const dateText=date ? date[1]+' '+date[2]+' '+String(date[3]||new Date().getFullYear()) : '';
const query=teams ? (teams[1]+' vs '+teams[2]+' '+dateText+' official schedule venue stadium location') : ('Find the official venue or physical destination for: '+String(base.destinationQuery||base.destination||objective));
return [{json:{query,max_results:5,objective,base}}];"""
    nodes["Render Travel Evidence"]["parameters"]["jsCode"] = """const base=$('Travel Tool Requested?').first().json; const evidence=$json.body||{}; const models=Array.isArray(evidence.recommendation_view_models)?evidence.recommendation_view_models:[]; const lodging=models.find(v=>v&&v.category==='lodging')||null; const destination=evidence.destination?.label||base.destination; const origin=evidence.origin?.label||base.origin; const route=evidence.map_view_model?.route||{}; const miles=typeof route.distance_m==='number'?Math.round(route.distance_m*0.000621371*10)/10:null; const ready=Boolean(evidence.ok&&evidence.map_view_model); const categories=models.filter(v=>v&&v.available&&Array.isArray(v.options)&&v.options.length).map(v=>String(v.category)); const cal=base.calendar_evidence; const calNote=cal?(cal.event_count?' I found '+cal.event_count+' calendar event'+(cal.event_count===1?'':'s')+' in that date window.':' Your calendar is clear in that date window.') : ''; const venueNote=base.destinationEvidence?'I verified the destination as '+destination+'. ':''; const spoken=ready?(venueNote+'I mapped the Mapbox drive from '+origin+' to '+destination+(miles!==null?' — about '+miles+' miles.':'')+(categories.length?' I put public '+categories.join(', ')+' options on the screen.':' The route is on the screen. The public listings provider did not return current lodging, meal, entertainment, or fuel listings.')+calNote+' I do not have live availability, reservations, or booking access.'):'I could not verify public Mapbox trip-planning evidence for that route.'; const publicCitations=(Array.isArray(base.citations)?base.citations:[]).filter(c=>c&&c.source_host!=='Google Calendar'); return [{json:{...base,status:ready?'COMPLETED':'NO_TRAVEL_EVIDENCE',spokenText:spoken,answer:ready?{...(base.answer||{}),origin,destination,route,notice:evidence.notice,trip_categories:categories}:{...(base.answer||{}),notice:'No verified trip-planning evidence.'},map_view_model:evidence.map_view_model||null,recommendation_view_model:lodging,trip_plan_view_model:ready?{schema:'jarvis.trip_plan_view_model.v1',emitted_by:'Jarvis II PA Tool',categories:models}:null,citations:ready?[...publicCitations,{title:'Mapbox trip planning',url:'https://www.mapbox.com/',source_host:'Mapbox'}]:[],auditChain:[...(Array.isArray(base.auditChain)?base.auditChain:[]),{stage:'trip_planning_evidence',status:ready?'completed':'not_found',source:evidence.source||null}]}}];"""
    OUTPUT.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")
    SOURCE.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
