from scripts.jarvis_ii_rag_core_service import resolve


def test_rejects_empty_query_without_touching_corpus():
    status, result = resolve({"query": ""})

    assert status == 400
    assert result["status"] == "INVALID_REQUEST"
