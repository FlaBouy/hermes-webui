#!/usr/bin/env python3
"""Keep evidence-verified venue labels in PA route presentation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"
OUTPUT = Path("/private/tmp/pa-core-verified-label.json")


def main() -> None:
    workflow = json.loads(SOURCE.read_text(encoding="utf-8"))[0]
    nodes = {entry["name"]: entry for entry in workflow["nodes"]}
    nodes["Render Travel Evidence"]["parameters"]["jsCode"] = """const base=$('Travel Tool Requested?').first().json; const evidence=$json.body||{}; const verifiedPlace=base.destinationEvidence?.place||null; const models=Array.isArray(evidence.recommendation_view_models)?evidence.recommendation_view_models:[]; const lodging=models.find(v=>v&&v.category==='lodging')||null; const destination=verifiedPlace?.label||evidence.destination?.label||base.destination; const spokenDestination=String(base.destinationEvidence?.query||destination).replace(/\\s+/g,' ').trim(); const origin=evidence.origin?.label||base.origin; const route=evidence.map_view_model?.route||{}; const miles=typeof route.distance_m==='number'?Math.round(route.distance_m*0.000621371*10)/10:null; const ready=Boolean(evidence.ok&&evidence.map_view_model); const categories=models.filter(v=>v&&v.available&&Array.isArray(v.options)&&v.options.length).map(v=>String(v.category)); const cal=base.calendar_evidence; const calNote=cal?(cal.event_count?' I found '+cal.event_count+' calendar event'+(cal.event_count===1?'':'s')+' in that date window.':' Your calendar is clear in that date window.') : ''; const venueNote=verifiedPlace?'I verified the destination as '+spokenDestination+'. ':''; const spoken=ready?(venueNote+'I mapped the Mapbox drive from '+origin+' to '+spokenDestination+(miles!==null?' — about '+miles+' miles.':'')+(categories.length?' I put public '+categories.join(', ')+' options on the screen.':' The route is on the screen. The public listings provider did not return current lodging, meal, entertainment, or fuel listings.')+calNote+' I do not have live availability, reservations, or booking access.'):'I could not verify public Mapbox trip-planning evidence for that route.'; const publicCitations=(Array.isArray(base.citations)?base.citations:[]).filter(c=>c&&c.source_host!=='Google Calendar'); const mapView=ready?{...evidence.map_view_model,destination:verifiedPlace?{...(evidence.map_view_model.destination||{}),...verifiedPlace,label:destination}:evidence.map_view_model.destination}:null; return [{json:{...base,status:ready?'COMPLETED':'NO_TRAVEL_EVIDENCE',spokenText:spoken,answer:ready?{...(base.answer||{}),origin,destination,route,notice:evidence.notice,trip_categories:categories}:{...(base.answer||{}),notice:'No verified trip-planning evidence.'},map_view_model:mapView,recommendation_view_model:lodging,trip_plan_view_model:ready?{schema:'jarvis.trip_plan_view_model.v1',emitted_by:'Jarvis II PA Tool',categories:models}:null,citations:ready?[...publicCitations,{title:'Mapbox trip planning',url:'https://www.mapbox.com/',source_host:'Mapbox'}]:[],auditChain:[...(Array.isArray(base.auditChain)?base.auditChain:[]),{stage:'trip_planning_evidence',status:ready?'completed':'not_found',source:evidence.source||null}]}}];"""
    OUTPUT.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")
    SOURCE.write_text(json.dumps([workflow], indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
