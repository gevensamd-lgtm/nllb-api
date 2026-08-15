from collections.abc import Iterator
from logging import getLogger
from pathlib import Path
from typing import Self

from ctranslate2 import Translator as CTranslator
from tokenizers import Tokenizer

from server.features.translator.protocol import TranslatorProtocol
from server.features.translator.stub import TranslatorStub
from server.typedefs import Language
from server.utils import huggingface_download

logger = getLogger(__name__)


class Translator(TranslatorProtocol):
    """
    Summary
    -------
    a class for the NLLB translator

    Methods
    -------
    translate_generator(text: str, source_language: Language, target_language: Language) -> Iterator[str]
        translate the input from the source language to the target language tokens

    translate(text: str, source_language: Language, target_language: Language) -> str
        translate the input from the source language to the target language

    translate_stream(text: str, source_language: Language, target_language: Language) -> Iterator[str]
        streams the translation input from the source language to the target language

    unload_model(to_cpu: bool) -> bool
        unload the model from the current device

    load_model(keep_cache: bool) -> bool
        load the model back to the initial device

    count_tokens(text: str) -> int
        count the number of tokens in the input text
    """

    __slots__ = ("tokeniser", "translator", "use_cuda")

    def __init__(self, translator: CTranslator, tokeniser: Tokenizer, *, use_cuda: bool) -> None:
        self.tokeniser = tokeniser
        self.translator = translator
        self.use_cuda = use_cuda

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        del self.tokeniser
        del self.translator

    def unload_model(self, *, to_cpu: bool) -> bool:
        """
        Summary
        -------
        unload the model from the current device

        Parameters
        ----------
        to_cpu (bool)
            whether to unload the model to CPU

        Returns
        -------
        success (bool)
            whether the model unload was executed
        """
        if not self.translator.model_is_loaded:
            return False

        self.translator.unload_model(to_cpu=self.use_cuda and to_cpu)
        return True

    def load_model(self, *, keep_cache: bool) -> bool:
        """
        Summary
        -------
        load the model back to the initial device

        Parameters
        ----------
        keep_cache (bool)
            whether to keep the model cache in RAM

        Returns
        -------
        success (bool)
            whether the model load was executed
        """
        if self.translator.model_is_loaded:
            return False

        self.translator.load_model(keep_cache=self.use_cuda and keep_cache)
        return True

    def count_tokens(self, text: str) -> int:
        """
        Summary
        -------
        count the number of tokens in the input text

        Parameters
        ----------
        text (str)
            the input text

        Returns
        -------
        token_count (int)
            the number of tokens that will be sent to the translator
        """
        return len(self.tokeniser.encode(text)) + 1

    def translate_generator(self, text: str, source_language: Language, target_language: Language) -> Iterator[int]:
        """
        Summary
        -------
        translate the input from the source language to the target language tokens

        Parameters
        ----------
        text (str)
            the input to translate

        source_language (Languages)
            the source language

        target_language (Languages)
            the target languages

        Returns
        -------
        token_indices (Iterator[int]) : the translated tokens indices
        """
        target_prefix = (target_language,)
        results = self.translator.generate_tokens(
            (source_language, *self.tokeniser.encode(text).tokens),
            target_prefix,
            max_decoding_length=1024,
            sampling_temperature=0,
            no_repeat_ngram_size=3,
            suppress_sequences=(target_prefix,),
        )

        return (result.token_id for result in results if not result.is_last)

    def translate(self, text: str, source_language: Language, target_language: Language) -> str:
        """
        Summary
        -------
        translate the input from the source language to the target language

        Parameters
        ----------
        text (str)
            the input to translate

        source_language (Languages)
            the source language

        target_language (Languages)
            the target language

        Returns
        -------
        translated_text (str)
            the translated text
        """
        return self.tokeniser.decode(tuple(self.translate_generator(text, source_language, target_language)))

    def translate_stream(self, text: str, source_language: Language, target_language: Language) -> Iterator[str]:
        """
        Summary
        -------
        streams the translation input from the source language to the target language

        Parameters
        ----------
        text (str)
            the input to translate

        source_language (Languages)
            the source language

        target_language (Languages)
            the target language

        Returns
        -------
        translated_text (Iterator[str])
            the translated text
        """

        return (
            self.tokeniser.decode((token,))
            for token in self.translate_generator(text, source_language, target_language)
        )

    def _encode_one(self, text: str, source_language: Language) -> list[str]:
        """
        Summary
        -------
        tokeniza UN texto para el camino batch

        Aislado en su propio metodo para que un fallo de tokenizacion de un item
        se pueda capturar por item sin abortar el lote (ver `translate_batch_texts`).
        """
        return [source_language, *self.tokeniser.encode(text).tokens]

    def translate_batch_texts(
        self, texts: list[str], source_language: Language, target_language: Language
    ) -> list[str | None]:
        """
        Summary
        -------
        traduce N textos en UNA pasada de CTranslate2 (`translate_batch`), en vez de N
        pasadas de `translate()`

        Contrato (igual que el endpoint single: NUNCA lanza):
        - `results[i]` corresponde a `texts[i]`; mismo largo, mismo orden que `texts`.
        - `None` = ese texto no se pudo traducir (vacio, o fallo puntual de
          tokenizacion/decodificacion); el resto del lote sigue.
        - texto vacio (o solo espacios) -> `None`, sin pasar por el traductor. Un texto
          vacio NUNCA se le manda a `translate_batch`: CTranslate2 no lanza ni devuelve
          vacio para ese caso, alucina una traduccion con forma valida pero sin
          relacion con el input (confirmado empiricamente, ver docs/BATCH-SPIKE-NOTES.md).
        - source_language == target_language -> se devuelve el original, sin gastar
          computo.

        Parameters
        ----------
        texts (list[str])
            los textos a traducir

        source_language (Language)
            el idioma origen

        target_language (Language)
            el idioma destino

        Returns
        -------
        translated_texts (list[str | None])
            la traduccion de cada texto, en el mismo orden y con el mismo largo que
            `texts`; `None` en la posicion de cualquier texto que no se pudo traducir
        """
        if not texts:
            return []

        # Atajo determinista antes de tocar el modelo: mismo criterio que el
        # driver single-text del cliente, ahora tambien server-side.
        if source_language == target_language:
            return list(texts)

        # Se tokeniza solo lo traducible y se recuerda de que posicion del
        # request vino cada uno — asi un vacio (o un fallo de tokenizacion)
        # deja SU posicion en None sin correr el resto del lote. El filtro de
        # vacios pasa ANTES de construir source_tokens: no hay señal post-hoc
        # (excepcion, hipotesis vacia) que permita detectarlos despues de
        # llamar a translate_batch.
        indices: list[int] = []
        source_tokens: list[list[str]] = []
        results: list[str | None] = [None] * len(texts)

        for i, text in enumerate(texts):
            if not text.strip():
                continue
            try:
                source_tokens.append(self._encode_one(text, source_language))
                indices.append(i)
            except Exception:  # noqa: BLE001 - un item roto no aborta el lote
                logger.warning("batch: fallo de tokenizacion en el item %d", i)

        if not source_tokens:
            return results

        target_prefix = [[target_language]] * len(source_tokens)

        try:
            batch = self.translator.translate_batch(
                source_tokens,
                target_prefix=target_prefix,
                max_decoding_length=1024,
                sampling_temperature=0,
                no_repeat_ngram_size=3,
                suppress_sequences=target_prefix,
            )
        except Exception:
            logger.exception("batch: translate_batch fallo para el lote completo")
            return results

        for position, translation in zip(indices, batch, strict=True):
            try:
                # hypotheses[0][0] es el token de idioma destino - saltearlo antes
                # de reconvertir a ids y decodificar (ver docs/BATCH-SPIKE-NOTES.md).
                hypothesis_tokens = translation.hypotheses[0][1:]
                token_ids = [self.tokeniser.token_to_id(token) for token in hypothesis_tokens]
                results[position] = self.tokeniser.decode(token_ids)
            except Exception:  # noqa: BLE001 - un item roto no aborta el lote
                logger.warning("batch: fallo al decodificar el item %d", position)

        return results


def get_translator(
    repository: str,
    *,
    translator_threads: int,
    stub: bool,
    testing: bool,
    use_cuda: bool,
) -> TranslatorProtocol:
    """
    Summary
    -------
    get the translator object

    Parameters
    ----------
    repository (str)
        the repository to download the model from

    translator_threads (int)
        the number of threads to use for the translator

    stub (bool)
        whether to return a stub translator for testing

    testing (bool)
        whether the application is running in integration testing mode

    use_cuda (bool)
        whether to use CUDA for inference

    Returns
    -------
    translator (TranslatorProtocol)
        the translator
    """
    if stub:
        return TranslatorStub()

    model_path = huggingface_download(repository)
    tokeniser = Tokenizer.from_file(str(Path(model_path) / "tokenizer.json"))
    translator = CTranslator(
        model_path,
        "cuda" if use_cuda else "cpu",
        compute_type="default" if testing else "auto",
        inter_threads=translator_threads,
    )

    return Translator(translator, tokeniser, use_cuda=use_cuda)
