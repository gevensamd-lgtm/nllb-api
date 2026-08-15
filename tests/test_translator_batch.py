# ruff: noqa: S101

from pytest import MonkeyPatch

from server.features.translator import TranslatorProtocol

MENSAJE_TOKENIZACION_ROTA = "fallo puntual de tokenizacion"


def test_orden_y_largo_de_results_coinciden_con_texts(translator: TranslatorProtocol) -> None:
    texts = ["Good morning", "The patient was discharged.", "Please confirm."]
    results = translator.translate_batch_texts(texts, "eng_Latn", "spa_Latn")

    assert len(results) == len(texts)
    # results[i] corresponde a texts[i] — el contrato entero depende de esto.
    assert all(result is None or isinstance(result, str) for result in results)
    assert results[0] is not None
    assert results[0] != texts[0]


def test_texto_vacio_devuelve_none_en_esa_posicion_sin_romper_el_resto(translator: TranslatorProtocol) -> None:
    texts = ["Good morning", "", "Thank you"]
    results = translator.translate_batch_texts(texts, "eng_Latn", "spa_Latn")

    assert len(results) == len(texts)
    assert results[1] is None
    assert results[0] is not None
    assert results[2] is not None

    # El bloqueante documentado en docs/BATCH-SPIKE-NOTES.md: CTranslate2 NO lanza ni
    # devuelve vacio para un string vacio, alucina una traduccion con forma valida
    # (ej. "¿Qué quieres decir?"). El filtro pre-batch debe evitar que ese texto
    # llegue siquiera a translate_batch — si el filtro fallara, results[1] seria una
    # alucinacion en vez de None.
    assert results[1] != "¿Qué quieres decir?"


def test_texto_solo_espacios_tambien_devuelve_none(translator: TranslatorProtocol) -> None:
    texts = ["Good morning", "   ", "Thank you"]
    results = translator.translate_batch_texts(texts, "eng_Latn", "spa_Latn")

    assert len(results) == len(texts)
    assert results[1] is None


def test_source_igual_a_target_devuelve_el_original_sin_computo(translator: TranslatorProtocol) -> None:
    texts = ["hola", "buenos dias"]
    assert translator.translate_batch_texts(texts, "spa_Latn", "spa_Latn") == texts


def test_un_item_que_falla_no_aborta_el_lote(translator: TranslatorProtocol, monkeypatch: MonkeyPatch) -> None:
    # Mismo espiritu que el endpoint single: nunca lanza. Se fuerza que la
    # tokenizacion del SEGUNDO texto explote y se verifica que 1 y 3 llegan bien.
    original = translator._encode_one  # type: ignore[attr-defined]

    def explosivo(text: str, source: str) -> list[str]:
        if text == "BOOM":
            raise RuntimeError(MENSAJE_TOKENIZACION_ROTA)
        return original(text, source)

    monkeypatch.setattr(translator, "_encode_one", explosivo)
    texts = ["Good morning", "BOOM", "Thank you"]
    results = translator.translate_batch_texts(texts, "eng_Latn", "spa_Latn")

    assert len(results) == len(texts)
    assert results[1] is None
    assert results[0] is not None
    assert results[2] is not None


def test_lote_vacio_devuelve_lista_vacia(translator: TranslatorProtocol) -> None:
    assert translator.translate_batch_texts([], "eng_Latn", "spa_Latn") == []
