"""Offline contracts for the Litestar query/body API migration."""

from collections.abc import Callable, Iterator
from hashlib import sha256
from json import loads
from pathlib import Path
from subprocess import PIPE, Popen
from sys import executable
from types import SimpleNamespace
from typing import TextIO
from unittest.mock import Mock

from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_400_BAD_REQUEST
from litestar.testing import AsyncTestClient
from nllb import AsyncTranslatorClient, TranslatorClient
from pytest import MonkeyPatch, fixture, raises

from server.config import Config
from server.model_integrity import MODEL_PINS, verify_snapshot

type ClientFactory = Callable[[Config], AsyncTestClient[Litestar]]


async def test_json_bodies_keep_single_and_batch_contracts(client_factory_without_lifespans: ClientFactory) -> None:
    translator = Mock()
    translator.translate.return_value = "hola"
    translator.translate_batch_texts.return_value = ["hola", None]
    client = client_factory_without_lifespans(Config())
    client.app.state.translator = translator
    async with client:
        single = await client.post("/v4/translator", json={"text": "hello", "source": "eng_Latn", "target": "spa_Latn"})
        batch = await client.post(
            "/v4/translator/batch", json={"texts": ["hello", ""], "source": "eng_Latn", "target": "spa_Latn"}
        )
        invalid = await client.post("/v4/translator/batch", json={"source": "eng_Latn", "target": "spa_Latn"})
    assert single.status_code == HTTP_200_OK
    assert single.json() == {"result": "hola"}
    assert batch.status_code == HTTP_200_OK
    assert batch.json() == {"results": ["hola", None]}
    assert invalid.status_code == HTTP_400_BAD_REQUEST
    translator.translate.assert_called_once_with("hello", "eng_Latn", "spa_Latn")
    translator.translate_batch_texts.assert_called_once_with(["hello", ""], "eng_Latn", "spa_Latn")


async def test_query_aliases_keep_threshold_values_and_bounds(client_factory_without_lifespans: ClientFactory) -> None:
    detector = Mock()
    detector.detect.return_value = SimpleNamespace(language="eng_Latn", confidence=0.9)
    client = client_factory_without_lifespans(Config())
    client.app.state.language_detector = detector
    async with client:
        response = await client.get(
            "/v4/language",
            params={
                "text": "hello",
                "fast-model-confidence-threshold": 0.7,
                "accurate-model-confidence-threshold": 0.2,
            },
        )
        invalid = await client.get("/v4/language", params={"text": "hello", "fast-model-confidence-threshold": 1.2})
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"language": "eng_Latn", "confidence": 0.9}
    assert invalid.status_code == HTTP_400_BAD_REQUEST
    detector.detect.assert_called_once_with("hello", fasttext_confidence_threshold=0.7, lingua_confidence_threshold=0.2)


def test_model_integrity_rejects_modified_artifact(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    payload = b"synthetic model fixture only"
    monkeypatch.setitem(MODEL_PINS, "synthetic/test-model", ("a" * 40, {"model.bin": sha256(payload).hexdigest()}))
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(payload)
    assert verify_snapshot("synthetic/test-model", str(tmp_path)) == str(tmp_path)
    artifact.write_bytes(b"changed synthetic fixture")
    with raises(RuntimeError, match="Model integrity mismatch"):
        verify_snapshot("synthetic/test-model", str(tmp_path))


_QUERY_SERVER = """
from http.server import BaseHTTPRequestHandler, HTTPServer
from json import dumps
from urllib.parse import parse_qs, urlsplit

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(dumps(parse_qs(urlsplit(self.path).query)), flush=True)
        body = dumps({"language": "eng_Latn", "confidence": 0.75}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
"""


@fixture
def native_query_server() -> Iterator[tuple[str, TextIO]]:
    # A separate process keeps the blocking Rust client independent of the GIL.
    with Popen([executable, "-u", "-c", _QUERY_SERVER], stdout=PIPE, text=True) as process:
        if process.stdout is None:
            message = "Synthetic query server has no output pipe"
            raise RuntimeError(message)
        port = int(process.stdout.readline())
        try:
            yield f"http://127.0.0.1:{port}", process.stdout
        finally:
            process.terminate()
            process.wait(timeout=5)


async def test_native_clients_forward_threshold_aliases(native_query_server: tuple[str, TextIO]) -> None:
    url, output = native_query_server
    prediction = TranslatorClient(base_url=url).detect_language(
        "synthetic text only", fast_model_confidence_threshold=0.5, accurate_model_confidence_threshold=0.25
    )
    async_prediction = await AsyncTranslatorClient(base_url=url).detect_language(
        "synthetic text only", fast_model_confidence_threshold=0.5, accurate_model_confidence_threshold=0.25
    )
    assert prediction.language == async_prediction.language == "eng_Latn"
    received = [loads(output.readline()), loads(output.readline())]
    expected = {
        "text": ["synthetic text only"],
        "fast-model-confidence-threshold": ["0.5"],
        "accurate-model-confidence-threshold": ["0.25"],
    }
    assert received == [expected, expected]
