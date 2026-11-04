import json
from types import SimpleNamespace as NS

import pytest

from ats.llm import ANALYSIS_SCHEMA, JD_SCHEMA, ClaudeLLM, LLMError, strict_schema


class BadRequest(Exception):
    status_code = 400


def make_llm(responses):
    llm = ClaudeLLM.__new__(ClaudeLLM)
    llm.model = "test-model"
    from ats.llm import _LRU

    llm.cache = _LRU()
    calls = []

    def create(**kw):
        calls.append(kw)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    llm.client = NS(messages=NS(create=create))
    return llm, calls


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


@pytest.mark.parametrize("schema", [JD_SCHEMA, ANALYSIS_SCHEMA])
def test_strict_schema_shape(schema):
    s = strict_schema(schema)
    for n in walk(s):
        assert not isinstance(n.get("type"), list)
        assert "minimum" not in n and "maximum" not in n
        if n.get("type") == "object" and "properties" in n:
            assert n["additionalProperties"] is False
            assert set(n["required"]) == set(n["properties"])


def test_structured_output_path():
    llm, calls = make_llm([NS(content=[NS(type="text", text=json.dumps({"title": "x"}))], stop_reason="end_turn")])
    assert llm.extract_jd("jd text " * 10) == {"title": "x"}
    assert "output_config" in calls[0] and "tools" not in calls[0]


def test_fallback_to_tool_on_400():
    tool_resp = NS(content=[NS(type="tool_use", input={"title": "y"})], stop_reason="tool_use")
    llm, calls = make_llm([BadRequest("400 output_config not supported"), tool_resp])
    assert llm.extract_jd("jd text " * 10) == {"title": "y"}
    assert calls[1]["tool_choice"] == {"type": "auto"}


def test_non_400_error_raises():
    llm, _ = make_llm([RuntimeError("connection reset")])
    with pytest.raises(LLMError):
        llm.extract_jd("jd text " * 10)


def test_cache_hits():
    llm, calls = make_llm([NS(content=[NS(type="text", text='{"a": 1}')], stop_reason="end_turn")])
    llm.extract_jd("same " * 20)
    llm.extract_jd("same " * 20)
    assert len(calls) == 1
