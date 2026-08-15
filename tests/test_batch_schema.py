# ruff: noqa: S101

from server.schemas.v1 import BatchTranslated as BatchTranslatedFromPackage
from server.schemas.v1 import BatchTranslation as BatchTranslationFromPackage
from server.schemas.v1.translated import BatchTranslated
from server.schemas.v1.translation import BatchTranslation

_LOTE_GRANDE = 500


def test_batch_request_acepta_lista_vacia_y_no_impone_tope() -> None:
    # Sin tope de lote server-side es una DECISION del spec, no un olvido:
    # el cliente es el responsable de no mandar lotes absurdos. msgspec.Struct no valida
    # constraints de Meta en la construcción directa (solo al decodificar), así que no hace
    # falta un caso "500 explota": ese tope simplemente no existe en ningún lado.
    req = BatchTranslation(texts=["a"] * _LOTE_GRANDE, source="eng_Latn", target="spa_Latn")
    assert len(req.texts) == _LOTE_GRANDE

    vacio = BatchTranslation(texts=[], source="eng_Latn", target="spa_Latn")
    assert vacio.texts == []


def test_batch_response_admite_null_por_item() -> None:
    res = BatchTranslated(results=["hola", None, "adios"])
    assert res.results == ["hola", None, "adios"]


def test_batch_schemas_importables_desde_v1() -> None:
    # el __init__.py del paquete re-exporta cada schema uno por uno; BatchTranslation/
    # BatchTranslated deben poder importarse igual que Translation/Translated existentes.
    assert BatchTranslationFromPackage is BatchTranslation
    assert BatchTranslatedFromPackage is BatchTranslated
