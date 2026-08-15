# Notas de implementación del endpoint batch

## Corrección del controlador (post-S1): el prefijo `/api` SÍ existe

Verificado en vivo contra prod (`curl https://nllb.corhild.com/api/v4/translator?...` → 200; el mismo path sin `/api` → 401 de OTRO router de Traefik, ni siquiera llega a este container) y confirmado por lectura de `server/config.py:107`: `server_root_path: str = "/api"` es el DEFAULT (sin env var), usado en `server/__init__.py` como `url_path_prefix=config.server_root_path` al montar la app ASGI. Las notas de abajo describen el router de Litestar relativo a ese montaje (`/v4/translator`), pero el path público real — el que S5 debe testear y el que Track C (`nllb-client.ts`) ya usa — es **`/api/v4/translator`**, y el batch nuevo será **`/api/v4/translator/batch`**. Ningún ajuste de código hace falta — el contrato ya documentado en el plan (`POST /api/v4/translator/batch`) era correcto; esto solo llena el hueco de POR QUÉ, para que S5 no se confunda si prueba local sin el `/api` y ve 404/401 inesperados.

## Paths reales (vs. lo que asumió el plan)
| Plan asumió | Real |
|---|---|
| server/api/v4/translator.py | **igual** — existe tal cual, `server/api/v4/translator.py` |
| server/schemas/v1/translation.py | **igual** — existe tal cual, `server/schemas/v1/translation.py` |
| server/features/translator/nllb.py | **igual** — existe tal cual, `server/features/translator/nllb.py` |

Los tres paths que el plan asumió a ciegas resultaron correctos letra por letra. Lo que **no** era correcto es el framework/librerías con las que están escritos (ver abajo) — el plan asumió FastAPI+Pydantic y el repo real usa **Litestar+msgspec**.

## Cómo traduce hoy el camino single-text
- **Framework HTTP: Litestar, NO FastAPI.** El plan (`## Global Constraints`, línea 9 del plan doc) dice "Python 3.x, FastAPI, Pydantic" — es incorrecto. `pyproject.toml` fija `litestar>=2.24.0`, `server/app.py` construye un `litestar.Litestar(...)`, y las rutas son `litestar.Controller` con decoradores `@get`/`@post`/`@put`/`@delete` de `litestar`, no `APIRouter`/`@router.get` de FastAPI.
- **Schemas: msgspec.Struct, NO Pydantic BaseModel.** `server/schemas/v1/translation.py` define `class Translation(Struct, kw_only=True, frozen=True, gc=False)` usando `msgspec.Meta` para las anotaciones (equivalente a `Field(...)` de Pydantic pero de otra librería). No hay ni un `BaseModel` en todo el módulo `server/schemas`.
- **Clase que envuelve CTranslate2:** `Translator` en `server/features/translator/nllb.py` (implementa el `Protocol` `TranslatorProtocol` de `server/features/translator/protocol.py`). Coincide con lo que el plan asumía.
  - Atributos (`__slots__`): `tokeniser` (instancia de `tokenizers.Tokenizer`, HuggingFace `tokenizers`, NO `transformers.AutoTokenizer`), `translator` (instancia de `ctranslate2.Translator`), `use_cuda: bool`.
- **Cómo se obtiene la instancia en la ruta: NO es `Depends()` de FastAPI.** Litestar inyecta el estado de la app directo como parámetro `state: AppState` en el handler (`AppState` es una subclase de `litestar.datastructures.State` definida en `server/typedefs/state.py`, con `translator: TranslatorProtocol` y `language_detector: LanguageDetectorProtocol` como atributos tipados). El traductor se instancia una sola vez en el lifespan (`server/lifespans/load_translator_model.py::translator_lifespan`), que llama a la factory `get_translator(...)` (definida al final de `nllb.py`) y asigna `app.state.translator = translator` dentro de un `with get_translator(...) as translator:` (el objeto es un context manager, `__enter__`/`__exit__` limpian `tokeniser`/`translator` al apagar). Todas las rutas existentes acceden a la instancia así: `state.translator.translate(text, source, target)`.
- **Tokenizer usado y cómo se aplica el token de idioma:** `tokenizers.Tokenizer` (HF `tokenizers`, cargado desde `tokenizer.json` del repo del modelo vía `Tokenizer.from_file(...)`). **No tiene** atributo `.src_lang` (eso es de `transformers.AutoTokenizer`, que este repo NO usa). El idioma origen se inyecta manualmente como PRIMER token de la secuencia de entrada:
  ```python
  results = self.translator.generate_tokens(
      (source_language, *self.tokeniser.encode(text).tokens),
      target_prefix=(target_language,),
      ...
  )
  ```
  El idioma destino se pasa como `target_prefix` (una tupla de UN elemento para el caso single, `(target_language,)`), no como parámetro separado del tokenizer. La decodificación usa `self.tokeniser.decode(tuple_de_token_ids)` — no hay `convert_ids_to_tokens`/`convert_tokens_to_ids` como asumía el plan (esos son métodos de `transformers`, no de `tokenizers.Tokenizer`; `tokenizers.Tokenizer` sí tiene `.encode(text).tokens` y `.encode(text).ids`, y `.decode(ids)` que ya hace la reconstrucción de texto).
- **Función exacta que la ruta llama hoy:** el handler `translator_post` (POST) y `translator_get` (GET) en `server/api/v4/translator.py` llaman **directo** a `state.translator.translate(text, source, target)` — no hay una capa intermedia de servicio.
- **Firma exacta de esa función:**
  ```python
  def translate(self, text: str, source_language: Language, target_language: Language) -> str
  ```
  (`Language` es un `Literal[...]` de códigos FLORES-200 en `server/typedefs/language.py`, no un `str` plano — pero acepta valores string vía el union type en tiempo de ejecución).
- **Internamente**, `translate()` llama a `translate_generator()`, que llama a `self.translator.generate_tokens(...)` — el objeto `ctranslate2.Translator` **NO** expone directamente un método `.translate()`/`.translate_batch()` usado hoy; el camino single usa `generate_tokens` (streaming token-by-token), no `translate_batch`. Esto es justo lo que S2 tiene que confirmar empíricamente: si `ctranslate2.Translator.translate_batch(...)` existe con la firma que asume S4 del plan, o si hay que construir el batch sobre `generate_batch`/otra API — **no se puede asumir por analogía con el camino single**, porque el camino single ni siquiera usa `translate_batch`.

## Framework de tests
- **Runner:** `pytest` (con plugins `pytest-env` y `hypothesis`; NO usa `unittest`).
- **Comando:** `uv run pytest` (ejecuta contra el entorno gestionado por `uv`; el proyecto usa `uv_build` como build-backend). Las env vars `TESTING=True` y `AUTH_TOKEN=testtoken` las inyecta automáticamente `pytest-env` vía `[tool.pytest_env]` en `pyproject.toml` — no hace falta exportarlas a mano. Para correr solo los tests de traducción: `uv run pytest tests/test_translate_api.py -v`.
- **Dónde viven:** `tests/` en la raíz del repo (no `server/tests/`). Archivo relevante para el batch: `tests/test_translate_api.py` (ahí viven los tests del endpoint `/v4/translator` existente — el test de regresión de S5 debe vivir ahí también, no en un archivo nuevo, para reusar los fixtures).
- **Cliente de test:** `litestar.testing.AsyncTestClient` (async, NO `fastapi.testclient.TestClient` síncrono). Los tests son `async def` y usan `await client.post(...)`/`await client.get(...)`. Fixtures relevantes en `tests/conftest.py`:
  - `client` (function-scoped, `Config()` fresco por test, útil para tests que tocan `load_model`/`unload_model`)
  - `session_client` (session-scoped, se reusa entre tests de solo-lectura como traducción — es el que deben usar los tests nuevos de batch, siguiendo el patrón de `test_translate_api.py`)
  - `auth_token` (fixture de sesión, valor `"test_token"`; pero la env var de `pytest-env` fija `AUTH_TOKEN=testtoken` — dos valores DISTINTOS conviven, el primero es el que usan los tests parametrizados de `load_model`/`unload_model` vía `Config()` reconstruida en el fixture `client`)
- Las rutas existentes se testean con paths completos `/v4/translator`, `/v4/translator/stream`, `/v4/translator/tokens` — el nuevo endpoint batch debería testearse en `/v4/translator/batch` (bajo el mismo `TranslatorController`, ver `## Ajustes al plan`).

## Versión de CTranslate2 instalada
- `4.8.1` — confirmado por `uv.lock` (`name = "ctranslate2"`, `version = "4.8.1"`), que es la resolución exacta pinneada por `pyproject.toml` (`ctranslate2>=4.8.1`). No hay contenedor corriendo todavía en este repo recién clonado, así que no se pudo correr `pip show ctranslate2` dentro de un container real — `uv.lock` es la fuente de verdad más fuerte disponible sin levantar el modelo (que requiere descargar pesos de Hugging Face). S2 debe re-confirmar esta versión dentro del container/entorno donde corra el spike, por si el lockfile diverge del entorno de ejecución real.
- Python: `requires-python = ">=3.14.6, <3.15"` — Python 3.14, más nuevo de lo que suele asumirse por defecto. Relevante para S6 (build de imagen Docker) si se asume una base image con otra versión de Python.

## Firma confirmada de translate_batch

Confirmado empíricamente corriendo `ctranslate2.Translator.translate_batch` real dentro del container
`ghcr.io/winstxnhdw/nllb-api:main` (mismo entorno que producción, levantado ad-hoc vía SSH contra el host
netcup — no hay Docker local en el entorno de desarrollo), con el modelo real descargado
(`winstxnhdw/nllb-200-distilled-1.3B-ct2-int8`, path
`~/.cache/huggingface/hub/models--winstxnhdw--nllb-200-distilled-1.3B-ct2-int8/snapshots/.../`) y el
tokenizer real (`tokenizers.Tokenizer.from_file(".../tokenizer.json")`).

- **Versión de ctranslate2 confirmada en el container real:** `4.8.1` (coincide con `uv.lock`; no se pudo
  correr `pip show` dentro del container porque no tiene `pip` ni ninguna shell utility instalada —
  imagen mínima sin `find`/`which`/`pip`, solo el intérprete Python. Se confirmó via
  `ctranslate2.__version__` en su lugar).
- **`translate_batch` SÍ existe** en `ctranslate2.Translator` (confirmado por
  `dir(ctranslate2.Translator)` → incluye `translate_batch`, `generate_tokens`, `score_batch`,
  `translate_file`, `translate_iterable`, entre otros). El plan NO tenía que caer a `generate_batch`
  (ese método no existe; no está en el `dir()`).
- **Firma real** (via `help(ctranslate2.Translator.translate_batch)`, coincide con la que S4 del plan
  asumió, con nombres de kwargs exactos):
  ```
  translate_batch(self, source: List[List[str]], target_prefix: Optional[List[Optional[List[str]]]] = None,
                   *, max_batch_size=0, batch_type='examples', beam_size=2, ...,
                   sampling_temperature=1, no_repeat_ngram_size=0, suppress_sequences=None, ...)
                   -> List[TranslationResult]
  ```
  `source` es una lista de listas de **tokens en texto** (`str`), NO de ids — igual que
  `generate_tokens` del camino single. `target_prefix` es una lista de listas de tokens de texto
  (un elemento por texto, cada uno una lista de UN token: el código de idioma destino), y acepta
  `None` por elemento si no se quiere forzar prefijo para ese texto puntual.
- **Llamada exacta que funciona** (copiada del script que corrió OK, ver salida abajo), calcada del
  patrón de `translate_generator()` existente pero en batch:
  ```python
  source_tokens = [(source_language, *tokeniser.encode(text).tokens) for text in texts]
  target_prefix = [[target_language]] * len(texts)

  results = translator.translate_batch(
      source_tokens,
      target_prefix=target_prefix,
      max_decoding_length=1024,
      sampling_temperature=0,
      no_repeat_ngram_size=3,
      suppress_sequences=[[target_language]] * len(texts),
  )

  for text, result in zip(texts, results):
      hyp = result.hypotheses[0]                       # lista de tokens (str), no ids
      ids = [tokeniser.token_to_id(tok) for tok in hyp[1:]]  # [0] es el token de idioma destino, SALTEARLO
      decoded = tokeniser.decode(ids)
  ```
  (los mismos kwargs de generación que ya usa `translate_generator()` en el camino single —
  `max_decoding_length=1024`, `sampling_temperature=0`, `no_repeat_ngram_size=3`,
  `suppress_sequences=(target_prefix,)` — se pasaron también en batch para reproducir el mismo
  comportamiento determinista; no son parte de la firma mínima de `translate_batch`, pero S4 debería
  mantenerlos por paridad con el resultado de `translate()` single-text.)
- **Forma del resultado:** `results[i]` es un `ctranslate2.TranslationResult`. `.hypotheses[0]` es una
  **lista de tokens de texto** (`list[str]`, ej. `['spa_Latn', '▁Buenos', '▁días', '▁.']`), NO una lista
  de ids — a diferencia de `generate_tokens()` (camino single), que sí produce ids directamente vía
  `result.token_id`. El **token de idioma destino ocupa la posición `0`** de cada hypothesis y **hay que
  saltearlo** (`hyp[1:]`) antes de decodificar — si no se salta, `tokeniser.token_to_id('spa_Latn')`
  devuelve un id real (no es basura) y contamina el texto decodificado con basura al inicio.
  Para reconstruir el texto: convertir cada token de vuelta a id con `tokeniser.token_to_id(tok)`
  (método de `tokenizers.Tokenizer`, no estaba documentado en las notas de S1 porque el camino single
  nunca lo necesita — `generate_tokens` ya da ids) y pasar la **lista** (no generador; `tokeniser.decode`
  requiere un `Sequence`, un generador lanza `TypeError: argument 'ids': 'generator' object is not an
  instance of 'Sequence'`) a `tokeniser.decode(ids)`.
- **Salida real del spike** (3 traducciones legibles + 1 caso vacío, ver punto siguiente):
  ```
  ctranslate2: 4.8.1
  len(results) == 4 esperado 4
  'Good morning' -> 'Buenos días .'
  'The patient was discharged yesterday.' -> 'El paciente fue dado de alta ayer.'
  'Please confirm receipt.' -> 'Por favor, confirme el recibo.'
  ```
  (el espacio antes del punto final en "días ." es un artefacto normal del detokenizador SentencePiece
  al reconstruir el token `▁.`, el mismo mecanismo que usa `translate()` single-text hoy — no es un bug
  introducido por el batch, no requiere fix en S4).
- **Diferencias vs. lo que asumió el plan:** el plan (y el ejemplo del brief de esta task) asumía
  `transformers.AutoTokenizer` con `convert_ids_to_tokens`/`convert_tokens_to_ids` — API equivocada,
  ya corregida por S1 (`tokenizers.Tokenizer` real). Además, el plan no anticipaba que `translate_batch`
  devuelve **tokens de texto**, no ids — obliga a un paso extra (`tokeniser.token_to_id`) que no existe
  en el camino single (`generate_tokens` ya entrega ids). Fuera de eso, la firma coincide con lo asumido:
  `source: list[list[str]]`, `target_prefix: list[list[str]]`, resultado con `.hypotheses[0]`.
- **¿Un texto vacío hace que `translate_batch` lance, o devuelve una hipótesis vacía?**
  **No lanza — devuelve una hipótesis NO vacía pero alucinada/sin sentido.** Con `texts[3] = ""`, el
  tokenizer produce `source_tokens[3] == ('eng_Latn', '</s>', '<unk>')` (sin tokens de contenido) y
  `translate_batch` igual genera una traducción: `'' -> '¿Qué quieres decir?'` ("What do you mean?" en
  español) — el modelo alucina una respuesta plausible en vez de fallar o devolver cadena vacía. **Esto
  confirma que S4 debe filtrar los textos vacíos ANTES de armar el batch** (excluirlos de
  `source_tokens`/`target_prefix` y reinsertar `""` en la posición correspondiente del resultado final
  sin pasar por el traductor) — depender de que `translate_batch` devuelva algo vacío o lance para
  detectarlo NO funciona, el output es indistinguible de una traducción real sin inspeccionar el input
  vacío de antemano.

## Ajustes al plan

Estos son los ajustes que S2–S5 deben aplicar ANTES de escribir código, por la brecha entre lo que el plan asumió (FastAPI+Pydantic, por lectura cero del repo real) y lo que el repo real usa (Litestar+msgspec). Nada de esto cambia el CONTRATO HTTP acordado con el cliente (`POST /v4/translator/batch` → `{"results": [...]}`, mismo shape que Task C1 ya asume) — solo cómo se implementa server-side.

1. **S3 — Schemas: `msgspec.Struct`, no `Pydantic BaseModel`.**
   `BatchTranslation`/`BatchTranslated` deben heredar de `msgspec.Struct` (`kw_only=True, frozen=True, gc=False`, igual que `Translation`/`Translated` ya existentes en el mismo archivo), usando `Annotated[..., Meta(...)]` de `msgspec` en vez de `Field(...)` de Pydantic. El test de S3 (`BatchTranslation(texts=["a"]*500, ...)`) sigue funcionando igual con `Struct` — la sintaxis de construcción por keyword no cambia — pero el import correcto es `from msgspec import Meta, Struct`, no `from pydantic import BaseModel`.

2. **S4 — Tokenizer: sin `.src_lang`, sin `convert_ids_to_tokens`/`convert_tokens_to_ids`.**
   El código de ejemplo de S4 (`self.tokenizer.src_lang = source`, `self.tokenizer.convert_ids_to_tokens(...)`) asume la API de `transformers.AutoTokenizer`. El repo real usa `tokenizers.Tokenizer` (HF `tokenizers`, atributo `self.tokeniser`, con "ei" — ojo al nombre exacto del atributo, `tokeniser` no `tokenizer`). El patrón real para un ítem individual, calcado de `translate_generator()` existente:
   ```python
   source_tokens = (source_language, *self.tokeniser.encode(text).tokens)
   ```
   y la decodificación real es `self.tokeniser.decode(token_ids)` (recibe IDs, no tokens de texto — comparar con `translate()` existente, que hace `self.tokeniser.decode(tuple(...))` sobre los IDs que devuelve `translate_generator`). S4 debe reescribir `_encode_one`/el paso de decode contra esta API real, no la de `transformers`.

3. **S4 — `translate_batch` de CTranslate2 sigue sin confirmar (bloqueado en S2).**
   El camino single-text HOY usa `self.translator.generate_tokens(...)`, no `translate_batch(...)`. El código de ejemplo de S4 asume `self.translator.translate_batch(source_tokens, target_prefix=[[target]] * len(source_tokens))` devolviendo objetos con `.hypotheses[0]` — eso es plausible para la API pública de `ctranslate2.Translator` (existe en versiones recientes), pero **no se puede confirmar por lectura del camino single**, porque el camino single nunca lo usa. S2 debe spikear esto contra CTranslate2 4.8.1 real antes de que S4 escriba una sola línea.

4. **S4 — Falta un logger en `nllb.py`.**
   El módulo `server/features/translator/nllb.py` HOY no importa ni usa `logging` en ningún lado (a diferencia de `server/app.py`, que sí tiene `getLogger(app_name)`). El código de ejemplo de S4 usa `logger.warning(...)`/`logger.exception(...)` sin definir `logger` — S4 debe agregar `from logging import getLogger` + `logger = getLogger(__name__)` al tope del archivo (siguiendo el patrón de `server/app.py`, que usa el nombre de la app; en un módulo de feature, `__name__` es lo estándar).

5. **S5 — Ruta nueva: método de `TranslatorController` (Litestar), no `@router.post` de FastAPI.**
   El código de ejemplo de S5 (`@router.post("/translator/batch")`, `async def translate_batch_route(request: BatchTranslation, translator: Annotated[Translator, Depends(get_translator)])`) no aplica tal cual. El patrón real es agregar un método a la clase `TranslatorController` en `server/api/v4/translator.py`, mismo patrón que `translator_post` ya en el archivo:
   ```python
   @post("/batch", status_code=HTTP_200_OK, sync_to_thread=True)
   def translator_batch(self, state: AppState, data: BatchTranslation) -> BatchTranslated:
       """
       Summary
       -------
       traduce N textos en una sola pasada; el GET/POST single-text no se tocan
       """
       return BatchTranslated(results=state.translator.translate_batch_texts(data.texts, data.source, data.target))
   ```
   Notar: (a) el decorador es `@post` de `litestar`, ya importado en el archivo; (b) el path del decorador es SOLO `"/batch"` — el controller ya tiene `path = "/translator"`, así que Litestar concatena a `/v4/translator/batch` automáticamente (poner `"/translator/batch"` ahí duplicaría el prefijo y rompería la ruta); (c) el traductor se obtiene de `state.translator`, NO de `Depends(get_translator)` — `get_translator` es la factory que usa el LIFESPAN para construir el objeto una sola vez al arrancar, no algo que se inyecte por-request; (d) `sync_to_thread=True` porque el método es `def` síncrona que bloquea en CPU (CTranslate2), igual que `translator_post`/`translator_get` existentes — si se escribe como `async def` en cambio, quitar ese kwarg.
   También hay que importar `BatchTranslation`/`BatchTranslated` en el header del archivo (junto a `Tokens, Translated, Translation` que ya se importan de `server.schemas.v1`) y agregarlos al `__init__.py` del paquete de schemas (`server/schemas/v1/__init__.py`), que hoy exporta explícitamente cada schema uno por uno.

6. **S5 — Tests: `AsyncTestClient` async, no `TestClient` de FastAPI.**
   Los tests de ejemplo de S5 (`def test_...(client): response = client.post(...)`) están escritos síncronos, estilo FastAPI `TestClient`. Deben ser `async def test_...(session_client: AsyncTestClient[Litestar]): response = await session_client.post(...)`, siguiendo EXACTO el patrón ya en `tests/test_translate_api.py` (que además define helpers `translate_post`/`translate_get` — conviene agregar un helper `translate_batch_post` simétrico ahí mismo, no un archivo de test nuevo).

7. **Contrato HTTP con el cliente (Task C1) — NO afectado por nada de lo anterior.**
   `POST /v4/translator/batch` con body `{"texts": [...], "source": "...", "target": "..."}` → `200 {"results": [...]}` sigue siendo exactamente lo que Task C1 (`translateBatchViaNllb`) ya asume y ya tiene tests escritos contra ese shape. Ninguno de los ajustes de arriba cambia el shape JSON — solo el código Python interno que lo produce. C1 puede implementarse sin esperar a que S2–S5 resuelvan el detalle de CTranslate2.
