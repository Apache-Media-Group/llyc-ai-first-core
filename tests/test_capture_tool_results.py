import types
import main


def _tool_use(tid, name, tin):
    return types.SimpleNamespace(type="tool_use", id=tid, name=name, input=tin)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(stop, content):
    return types.SimpleNamespace(
        stop_reason=stop, content=content,
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=20),
    )


class _FakeClient:
    def __init__(self, responses):
        self._r = list(responses)
        self._i = 0
        self.messages = self

    def create(self, **kwargs):
        r = self._r[self._i]
        self._i += 1
        return r


def test_capture_shape_result_dict_and_dates():
    tin = {"date_start": "2026-06-09", "date_end": "2026-06-09"}
    hres = {"status": "ok", "data": {"spend_eur": 123.45, "revenue_eur": 678.9}}
    client = _FakeClient([
        _resp("tool_use", [_tool_use("toolu_1", "get_meta_performance", tin)]),
        _resp("end_turn", [_text('{"agent": "performance-monitor", "summary": "ok"}')]),
    ])
    output, captured = main.run_agent(
        client, "sys", [], "msg", lambda n, i: hres, "vidal-vidal", "performance-monitor"
    )
    assert output["agent"] == "performance-monitor"          # contrato intacto
    assert len(captured) == 1
    item = captured[0]
    assert set(item.keys()) == {"tool", "input", "result"}    # shape exacta
    assert item["tool"] == "get_meta_performance"
    assert isinstance(item["result"], dict)                   # dict nativo, no string
    assert item["result"]["data"]["spend_eur"] == 123.45
    assert item["input"]["date_start"] == "2026-06-09"        # ventana para T4
    assert item["input"]["date_end"] == "2026-06-09"


def test_capture_on_handler_exception_same_shape():
    def boom(n, i):
        raise RuntimeError("tool bug")
    client = _FakeClient([
        _resp("tool_use", [_tool_use("toolu_1", "get_google_ads_performance",
                                     {"date_start": "2026-06-09", "date_end": "2026-06-09"})]),
        _resp("end_turn", [_text('{"agent": "performance-monitor"}')]),
    ])
    output, captured = main.run_agent(
        client, "sys", [], "msg", boom, "vidal-vidal", "performance-monitor"
    )
    assert len(captured) == 1
    assert set(captured[0].keys()) == {"tool", "input", "result"}
    assert captured[0]["result"]["status"] == "error"
    assert "tool bug" in captured[0]["result"]["message"]
