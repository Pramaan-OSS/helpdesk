"""Schema boundary and the complete inventory of current generation payloads."""
import ast
import json
import unittest
from pathlib import Path
from test_pramaan_stubs import boundary, FakeTransport


class GenerationSchemas(unittest.TestCase):
    def test_every_real_generation_payload_and_schema_is_checked(self):
        root = Path(__file__).resolve().parents[1] / "helpdesk"
        callers = []
        schema_count = 0
        for file in root.rglob("*.py"):
            if file.name.startswith("test_") or "tests" in file.parts:
                continue
            for call in ast.walk(ast.parse(file.read_text())):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr not in {"call", "run"} or len(call.args) < 2:
                    continue
                cap = call.args[0]
                if not isinstance(cap, ast.Constant) or cap.value not in {"llm.chat", "llm.complete"}:
                    continue
                callers.append(file.relative_to(root).as_posix())
                payload = call.args[1]
                self.assertIsInstance(payload, ast.Dict, "Inventory must cover dynamically built payloads too")
                fields = {key.value: value for key, value in zip(payload.keys, payload.values) if isinstance(key, ast.Constant)}
                self.assertIn("messages", fields)
                self.assertNotIn("prompt", fields)
                # Current reply/article drafts request plain text: no schemas.
                # A new schema must be literal and pass this shared boundary, or
                # gain a runtime inventory test before it can be added here.
                if "jsonSchema" in fields:
                    boundary.normalise_json_schema(ast.literal_eval(fields["jsonSchema"]))
                    schema_count += 1
                if "tools" in fields:
                    for tool in ast.literal_eval(fields["tools"]):
                        boundary.normalise_json_schema(tool["parameters"], "Tool " + tool["name"])
                        schema_count += 1
        self.assertEqual(callers, ["api/capabilities.py", "api/capabilities.py"])
        self.assertEqual(schema_count, 0, "Update inventory when a real schema is introduced")

    def test_normalisation_drops_only_annotations_and_preserves_property_names_and_literals(self):
        schema = {"type": "object", "$schema": "draft", "properties": {
            "format": {"type": "string", "format": "email", "default": {"pattern": "literal"}}},
            "required": ["format"], "additionalProperties": False}
        normalized = boundary.normalise_json_schema(schema)
        self.assertEqual(normalized, {"type": "object", "properties": {"format": {
            "type": "string", "default": {"pattern": "literal"}}}, "required": ["format"], "additionalProperties": False})
        self.assertIn("format", schema["properties"]["format"])

    def test_disallowed_constraints_name_the_tool_and_nested_path_before_transport(self):
        for keyword in ("pattern", "oneOf", "allOf", "not", "uniqueItems"):
            with self.subTest(keyword=keyword):
                fake = FakeTransport()
                client = boundary.PramaanClient(api_key="fake", transport=fake)
                with self.assertRaises(boundary.InvalidGenerationRequest) as raised:
                    client.call("llm.chat", {"messages": [{"role": "user", "content": "Hello"}],
                        "tools": [{"name": "lookup", "parameters": {"type": "object", "properties": {"value": {keyword: "refused"}}}}]})
                self.assertIn(f"Tool lookup schema at #/properties/value/{keyword}", str(raised.exception))
                self.assertEqual(fake.requests, [])

    def test_limits_and_local_references(self):
        good = {"type": "object", "$defs": {"value": {"type": "string"}}, "properties": {"value": {"$ref": "#/$defs/value"}}}
        boundary.validate_json_schema(good)
        invalid = [[], {"type": "object", "description": "a" * 65536},
            {"type": "object", "properties": {"x": {"anyOf": [{"type": "string"}] * 17}}},
            {"type": "object", "properties": {"x": {"enum": list(range(257))}}},
            {"type": "object", "$ref": "https://example.test/schema"},
            {"type": "object", "$ref": "#/$defs/missing"},
            {"type": "object", "$defs": {"value": {"$ref": "#/$defs/value"}}},
            {"type": "object", "properties": {str(i): {"type": "string"} for i in range(256)}}]
        for schema in invalid:
            with self.subTest(schema=str(schema)[:50]), self.assertRaises(boundary.InvalidGenerationRequest):
                boundary.validate_json_schema(schema)
        boundary.validate_json_schema({"type": "object", "properties": {str(i): {"type": "string"} for i in range(255)}})
        deep = {"type": "string"}
        for _ in range(16):
            deep = {"type": "array", "items": deep}
        boundary.validate_json_schema(deep)
        with self.assertRaises(boundary.InvalidGenerationRequest):
            boundary.validate_json_schema({"type": "array", "items": deep})

    def test_messages_and_safe_token_default_on_both_capabilities(self):
        for capability in ("llm.chat", "llm.complete"):
            fake = FakeTransport()
            client = boundary.PramaanClient(api_key="fake", transport=fake)
            client.call(capability, {"messages": [{"role": "user", "content": "Hello"}],
                "jsonSchema": {"type": "object", "$schema": "draft", "properties": {"x": {"type": "string", "format": "email"}}}})
            body = fake.requests[0][3]
            self.assertEqual(body["maxTokens"], 1024)
            self.assertNotIn("prompt", body)
            self.assertNotIn("$schema", body["jsonSchema"])
            self.assertNotIn("format", body["jsonSchema"]["properties"]["x"])
            client.call(capability, {"messages": [{"role": "user", "content": "Hello"}], "maxTokens": 64})
            self.assertEqual(len(fake.requests), 2)
            for payload in ({"prompt": "Hello"}, {"messages": []}, {"messages": ["Hello"], "maxTokens": 64}, {"messages": [{"role": "user", "content": "Hello"}], "maxTokens": 8}):
                with self.assertRaises(boundary.InvalidGenerationRequest):
                    client.call(capability, payload)
            self.assertEqual(len(fake.requests), 2)

    def test_fake_refuses_unsupported_wire_schemas_and_low_tokens(self):
        fake = FakeTransport()
        for payload in ({"messages": [{"role": "user", "content": "Hello"}], "maxTokens": 8},
                        {"messages": [{"role": "user", "content": "Hello"}], "maxTokens": 64, "jsonSchema": {"type": "object", "format": "refused"}},
                        {"messages": [{"role": "user", "content": "Hello"}], "maxTokens": 64, "tools": [{"name": "lookup", "parameters": {"type": "object", "$schema": "refused"}}]}):
            with self.assertRaises(boundary.InvalidGenerationRequest):
                fake("POST", "https://pramaan.test/v1/capabilities/llm.complete", {}, payload)
        self.assertEqual(fake.requests, [])

    def test_all_mail_voice_and_transcription_capabilities_have_safe_unavailable_messages(self):
        caps = [cap for cap in boundary.PramaanClient.CAPABILITIES if cap.startswith(("email.", "voice.")) or cap == "audio.transcription.create"]
        for cap in caps:
            requests = []
            def unavailable(*args):
                requests.append(args)
                return 502, {"error": {"code": "upstream_unavailable", "message": "private upstream diagnostics"}}
            client = boundary.PramaanClient(api_key="fake", transport=unavailable)
            with self.subTest(capability=cap), self.assertRaises(boundary.PramaanNotAvailable) as raised:
                client.call(cap, {}, idempotency_key="fixture" if cap in client.ACTIONS else None)
            self.assertIn("not available yet", str(raised.exception))
            self.assertNotIn("private", str(raised.exception))
            self.assertFalse(raised.exception.uncertain)
            self.assertEqual(raised.exception.http_status_code, 503)
            self.assertEqual(len(requests), 1)

    def test_unknown_failure_remains_uncertain_and_is_never_resent(self):
        requests = []
        client = boundary.PramaanClient(api_key="fake", transport=lambda *a: requests.append(a) or (500, {"error": "unknown"}))
        with self.assertRaises(boundary.PramaanError) as raised:
            client.call("voice.call.start-configured", {}, idempotency_key="fixture")
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(len(requests), 1)
