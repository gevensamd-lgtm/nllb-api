from typing import Annotated

from msgspec import Meta, Struct


class Translated(Struct, kw_only=True, frozen=True, gc=False):
    """
    Summary
    -------
    the translated schema

    Attributes
    ----------
    result (str)
        the translated text
    """

    result: Annotated[
        str,
        Meta(
            description="translated text in the language specified within the `target` request field",
            examples=["¡Hola, mundo!"],
        ),
    ]


class BatchTranslated(Struct, kw_only=True, frozen=True, gc=False):
    """
    Summary
    -------
    the batch translated schema

    Attributes
    ----------
    results (list[str | None])
        translated texts, in the exact same length and order as `texts` from the request; `None`
        at a given position means that particular text could not be translated, the rest of the
        batch is unaffected
    """

    results: Annotated[
        list[str | None],
        Meta(
            description="translated texts, same length and order as the request's `texts`; "
            "`None` marks a single text that could not be translated",
            examples=[["¡Hola, mundo!", None]],
        ),
    ]
