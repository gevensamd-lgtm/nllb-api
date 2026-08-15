from typing import Annotated

from msgspec import Meta, Struct

from server.typedefs import Language


class Translation(Struct, kw_only=True, frozen=True, gc=False):
    """
    Summary
    -------
    the NLLB translation schema

    Attributes
    ----------
    text (str)
        source text of a single language

    source (Language)
        source language in the FLORES-200 code format

    target (Language)
        target language in the FLORES-200 code format
    """

    text: Annotated[
        str,
        Meta(min_length=1, max_length=4096, description="source text of a single language", examples=["Hello, world!"]),
    ]

    source: Annotated[
        Language, Meta(description="source language in the FLORES-200 code format", examples=["eng_Latn"])
    ]

    target: Annotated[
        Language, Meta(description="target language in the FLORES-200 code format", examples=["spa_Latn"])
    ]


class BatchTranslation(Struct, kw_only=True, frozen=True, gc=False):
    """
    Summary
    -------
    the NLLB batch translation schema

    Attributes
    ----------
    texts (list[str])
        source texts to translate in a single pass, in the same language pair; no server-side
        cap on the number of texts, the caller is responsible for not sending unreasonable batches

    source (Language)
        source language in the FLORES-200 code format

    target (Language)
        target language in the FLORES-200 code format
    """

    texts: Annotated[
        list[str],
        Meta(description="source texts to translate in a single pass", examples=[["Hello, world!", "Good morning"]]),
    ]

    source: Annotated[
        Language, Meta(description="source language in the FLORES-200 code format", examples=["eng_Latn"])
    ]

    target: Annotated[
        Language, Meta(description="target language in the FLORES-200 code format", examples=["spa_Latn"])
    ]
