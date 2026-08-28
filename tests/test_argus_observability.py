from __future__ import annotations

import json


def test_flight_recorder_is_correlation_bound_and_redacts(monkeypatch, tmp_path):
    import api.argus_observability as obs

    monkeypatch.setattr(obs, "_ROOT", tmp_path)
    event = obs.record_event(
        "corr-123",
        component="smedley",
        stage="retrieve",
        status="completed",
        duration_ms=41.6,
        authorization="Bearer never-write-this",
        source_count=3,
    )

    assert event["correlation_id"] == "corr-123"
    assert event["duration_ms"] == 42
    assert event["attributes"]["authorization"] == "[redacted]"
    saved = list(tmp_path.glob("*.jsonl"))
    assert len(saved) == 1
    payload = json.loads(saved[0].read_text().strip())
    assert payload["stage"] == "retrieve"
    assert "never-write-this" not in saved[0].read_text()


def test_execution_recovery_selects_terminal_result_for_exact_correlation():
    from api.argus_n8n_recovery import _matching_result

    execution = {
        "data": {
            "resultData": {
                "runData": {
                    "Return PA Response": [
                        {
                            "data": {
                                "main": [[
                                    {"json": {"correlationId": "other", "status": "COMPLETED", "spokenText": "Wrong"}},
                                    {"json": {"correlationId": "wanted", "status": "COMPLETED", "spokenText": "Right"}},
                                ]]
                            }
                        }
                    ]
                }
            }
        }
    }

    result = _matching_result(execution, "wanted")
    assert result is not None
    assert result["spokenText"] == "Right"
