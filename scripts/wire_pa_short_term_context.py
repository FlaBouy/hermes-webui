#!/usr/bin/env python3
"""Wire bounded Biggy session context into the active PA planner prompt.

The context is a volatile, per-chat reference only.  It cannot supply
technical facts or citations and cannot replace a fresh approved tool call.
"""

from __future__ import annotations

import json
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "jarvis-ii-pa-core-poc.json"


def main() -> None:
    raw = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    workflow = raw[0] if isinstance(raw, list) else raw
    nodes = {node["name"]: node for node in workflow["nodes"]}
    node = nodes["Build 120B Plan Request"]
    code = str(node["parameters"]["jsCode"])

    old_request = "const request = $('Validate PA Request').first().json;"
    new_request = "const request = $('Validate PA Request').first().json;\nconst conversationContext = Array.isArray(request.conversationContext) ? request.conversationContext.slice(-10) : [];"
    if new_request not in code:
        if old_request not in code:
            raise RuntimeError("PA planner request anchor not found")
        code = code.replace(old_request, new_request, 1)

    old_context = "Durable memory writes are forbidden. Context: '+JSON.stringify(context);"
    new_context = (
        "Durable memory writes are forbidden. Short-term conversation context is a volatile, same-chat target reference only; "
        "it may recover the subject of an explicit follow-up such as yes, dig deeper, or pull that figure, but it is never evidence. "
        "Never use it to state facts, manual titles, page numbers, citations, or results. Always call the approved tool and perform fresh verification. "
        "Durable strategy context may select only an approved tool and can never cache or answer a request. Durable context: '+JSON.stringify(context)+'. "
        "Short-term conversation context: '+JSON.stringify(conversationContext);"
    )
    if new_context not in code:
        if old_context not in code:
            raise RuntimeError("PA planner context anchor not found")
        code = code.replace(old_context, new_context, 1)
    node["parameters"]["jsCode"] = code

    governed = nodes["Governed PA Response"]
    governed_code = str(governed["parameters"]["jsCode"])
    old_objective = "const requested=rawTools.map(canonical).filter(x=>['rag_core','weather','maps','lodging_poi','calendar_read','gmail_read','research'].includes(String(x))); const objective=String(req.objective||'');"
    new_objective = "const requested=rawTools.map(canonical).filter(x=>['rag_core','weather','maps','lodging_poi','calendar_read','gmail_read','research'].includes(String(x))); const objective=String(req.objective||''); const shortTermTurns=Array.isArray(req.conversationContext)?req.conversationContext.slice(-10):[]; const followUp=/^(?:yes|yeah|yep|please|selection\\s*\\d+|option\\s*\\d+)\\b|\\b(?:dig\\s+deeper|pull\\s+(?:that|the)\\s+(?:figure|page|manual|schematic)|previous\\s+(?:manual|figure|page|schematic)|take\\s+a\\s+look)\\b/i.test(objective.trim()); const priorRagTurn=followUp?[...shortTermTurns].reverse().find(turn=>turn&&Array.isArray(turn.tools)&&turn.tools.includes('rag_core')&&String(turn.objective||'').trim()):null; const recoveredTarget=priorRagTurn?String(priorRagTurn.objective).trim().slice(0,500):''; const effectiveRagObjective=recoveredTarget?(recoveredTarget+' Follow-up request: '+objective).slice(0,700):objective;"
    if new_objective not in governed_code:
        if old_objective not in governed_code:
            raise RuntimeError("PA governed objective anchor not found")
        governed_code = governed_code.replace(old_objective, new_objective, 1)
    old_destination = "const destination=ragRequested?objective:(eventDestination?'':plannedDestination);"
    new_destination = "const destination=ragRequested?effectiveRagObjective:(eventDestination?'':plannedDestination);"
    if new_destination not in governed_code:
        if old_destination not in governed_code:
            raise RuntimeError("PA RAG destination anchor not found")
        governed_code = governed_code.replace(old_destination, new_destination, 1)
    old_audit = "auditChain:[...req.auditChain,{stage:'local_120b_plan',status:'completed',model:'openai/gpt-oss-120b'},{stage:'policy',status:'enforced'}]"
    new_audit = "auditChain:[...req.auditChain,{stage:'short_term_context',status:recoveredTarget?'target_recovered':'not_used',turns:shortTermTurns.length},{stage:'local_120b_plan',status:'completed',model:'openai/gpt-oss-120b'},{stage:'policy',status:'enforced'}]"
    if new_audit not in governed_code:
        if old_audit not in governed_code:
            raise RuntimeError("PA governed audit anchor not found")
        governed_code = governed_code.replace(old_audit, new_audit, 1)
    governed["parameters"]["jsCode"] = governed_code
    WORKFLOW.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
