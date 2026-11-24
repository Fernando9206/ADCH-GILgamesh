"""
dataset_generator.py
---------------------
Generador de escenarios de auditoria sinteticos y reproducibles (RF-02).

Produce un conjunto de "hashes objetivo" (simulando una base de datos de
credenciales filtrada) a partir de contraseñas de tres niveles de
complejidad:

  - debil:   palabra exacta del diccionario base (ej. "password", "dragon").
             El motor de mutaciones la encuentra casi de inmediato.
  - media:   palabra del diccionario + variacion de mayusculas + sufijo
             numerico y/o simbolo (ej. "Dragon99", "Shadow1234!").
             Requiere que el motor de mutaciones explore esa combinacion.
  - fuerte:  cadena aleatoria larga (letras, digitos y simbolos, 16
             caracteres). Esta FUERA del espacio de busqueda
             del diccionario, por lo que el sistema no debe poder
             recuperarla: se usa para demostrar, de forma responsable,
             que las contraseñas largas y aleatorias resisten el ataque.

Se usa `random.Random(seed)` para la seleccion/combinacion de piezas, de
forma que el mismo `seed` siempre reproduce exactamente el mismo dataset
(requisito explicito de reproducibilidad del RF-02).

Importante: el sistema solo recibe los HASHES (RF-01). La contraseña en
texto plano de cada usuario sintetico se guarda unicamente en un archivo
de "referencia de verificacion" (ground truth) separado, pensado para que
el equipo valide sus propios resultados durante la demostracion; el motor
de auditoria (sequential_auditor / parallel_auditor) nunca lee ese archivo.
"""

from __future__ import annotations

import csv
import string
from pathlib import Path
from random import Random
from typing import List, NamedTuple

from .hash_engine import (
    calcular_hash,
    detectar_algoritmo_por_longitud,
    normalizar_algoritmo,
    tamano_hash_hex,
)
from .dictionary import SIMBOLOS, cargar_diccionario

NIVELES = ("debil", "media", "fuerte")
# Distribucion por defecto: mas contraseñas debiles/medias (mas realista en
# fugas reales) y algunas fuertes para mostrar el caso de "no descifrable".
DISTRIBUCION_DEFECTO = {"debil": 0.40, "media": 0.40, "fuerte": 0.20}


class RegistroObjetivo(NamedTuple):
    usuario_id: str
    hash: str
    algoritmo: str


class RegistroReferencia(NamedTuple):
    usuario_id: str
    password: str
    nivel: str
    algoritmo: str


def _password_debil(rng: Random, palabras: List[str]) -> str:
    return rng.choice(palabras)


def _password_media(rng: Random, palabras: List[str]) -> str:
    """
    Contraseña de complejidad media: palabra de diccionario + variacion de
    mayusculas + sufijo numerico + (a veces) simbolo.

    El sufijo se elige del MISMO universo que explora el motor de
    mutaciones (patrones comunes, años 1990-2029 o 0-99): asi, en modo
    normal (--extendido no activado) solo una parte de estas contraseñas
    es recuperable, y en modo --extendido el motor las encuentra casi
    todas. Esto demuestra de forma medible el valor de un ataque mas
    exhaustivo (RF-02 / RF-03), en lugar de usar un sufijo 0-9999
    totalmente fuera de cualquier espacio de busqueda razonable.
    """
    from .dictionary import AÑOS, PATRONES_NUMERICOS_COMUNES

    palabra = rng.choice(palabras)
    variante = rng.choice([palabra.lower(), palabra.capitalize(), palabra.upper()])
    pool_sufijos = PATRONES_NUMERICOS_COMUNES + AÑOS + [str(n) for n in range(0, 100)]
    sufijo = rng.choice(pool_sufijos)
    usar_simbolo = rng.random() < 0.6
    simbolo = rng.choice(SIMBOLOS) if usar_simbolo else ""
    return f"{variante}{sufijo}{simbolo}"


def _password_fuerte(rng: Random, longitud: int = 16) -> str:
    alfabeto = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    # secrets.choice no acepta un rng externo; para mantener reproducibilidad
    # usamos rng.choice (random.Random) con una semilla fija dada por el caller.
    # (secrets se reserva para usos que requieran aleatoriedad criptografica
    # real; aqui priorizamos reproducibilidad del dataset de prueba.)
    return "".join(rng.choice(alfabeto) for _ in range(longitud))


def generar_dataset(
    n: int,
    algoritmo: str,
    diccionario_path: str | Path,
    seed: int = 42,
    distribucion: dict | None = None,
) -> tuple[List[RegistroObjetivo], List[RegistroReferencia]]:
    """
    Genera `n` registros (5 <= n <= 50 recomendado por el enunciado, pero
    no se restringe duro para permitir benchmarks mas grandes).

    Devuelve (objetivos, referencia):
      - objetivos: lo que el sistema de auditoria recibira (usuario_id, hash).
      - referencia: contraseñas en claro + nivel, SOLO para verificacion humana.
    """
    if n <= 0:
        raise ValueError("n debe ser un entero positivo")
    distribucion = distribucion or DISTRIBUCION_DEFECTO
    palabras = cargar_diccionario(diccionario_path)
    rng = Random(seed)

    # Construir la lista de niveles segun la distribucion (reproducible)
    niveles_asignados = []
    for nivel, proporcion in distribucion.items():
        niveles_asignados += [nivel] * round(n * proporcion)
    while len(niveles_asignados) < n:
        niveles_asignados.append("media")
    niveles_asignados = niveles_asignados[:n]
    rng.shuffle(niveles_asignados)

    objetivos: List[RegistroObjetivo] = []
    referencia: List[RegistroReferencia] = []

    for i, nivel in enumerate(niveles_asignados, start=1):
        usuario_id = f"usuario_{i:03d}"
        if nivel == "debil":
            password = _password_debil(rng, palabras)
        elif nivel == "media":
            password = _password_media(rng, palabras)
        else:
            password = _password_fuerte(rng)

        h = calcular_hash(password, algoritmo)
        objetivos.append(RegistroObjetivo(usuario_id, h, algoritmo))
        referencia.append(RegistroReferencia(usuario_id, password, nivel, algoritmo))

    return objetivos, referencia


def guardar_objetivos_csv(objetivos: List[RegistroObjetivo], ruta: str | Path) -> None:
    """Guarda (usuario_id, hash, algoritmo) -> esto es lo que 'recibe' el auditor."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["usuario_id", "hash", "algoritmo"])
        for obj in objetivos:
            writer.writerow([obj.usuario_id, obj.hash, obj.algoritmo])


def guardar_referencia_csv(referencia: List[RegistroReferencia], ruta: str | Path) -> None:
    """Guarda la referencia de verificacion (NO es entrada del auditor)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["usuario_id", "password", "nivel", "algoritmo"])
        for ref in referencia:
            writer.writerow([ref.usuario_id, ref.password, ref.nivel, ref.algoritmo])


def _validar_consistencia_algoritmo(objetivos: List[RegistroObjetivo], ruta: Path) -> None:
    """
    Verifica que la longitud hexadecimal de cada hash coincida con el
    algoritmo declarado para ese registro (RF-07). Si no coincide, falla
    de forma clara e inmediata en vez de dejar que la auditoria corra y
    "silenciosamente" recupere 0 contraseñas por un desajuste de
    algoritmo (bug detectado en docs/ANALISIS_PROYECTO.md §3.5).
    """
    for obj in objetivos:
        esperado = tamano_hash_hex(obj.algoritmo)
        if len(obj.hash) != esperado:
            detectado = None
            try:
                detectado = detectar_algoritmo_por_longitud(obj.hash)
            except ValueError:
                pass
            sugerencia = f" (por su longitud, parece ser {detectado.upper()})" if detectado else ""
            raise ValueError(
                f"Inconsistencia de algoritmo en '{ruta}': el usuario '{obj.usuario_id}' "
                f"declara algoritmo='{obj.algoritmo}' (hash de {esperado} caracteres) pero su "
                f"hash tiene {len(obj.hash)} caracteres{sugerencia}. Revisa --algoritmo o el archivo."
            )


def cargar_objetivos_csv(ruta: str | Path) -> List[RegistroObjetivo]:
    """RF-01: importar un archivo CSV con hashes objetivo + usuario_id."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro el archivo de hashes objetivo: {ruta}")
    objetivos = []
    with ruta.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for fila in reader:
            objetivos.append(
                RegistroObjetivo(fila["usuario_id"], fila["hash"].strip().lower(), fila["algoritmo"])
            )
    if not objetivos:
        raise ValueError(f"El archivo de hashes objetivo '{ruta}' esta vacio.")
    _validar_consistencia_algoritmo(objetivos, ruta)
    return objetivos


def cargar_objetivos_texto(ruta: str | Path) -> List[RegistroObjetivo]:
    """
    RF-01/RF-07: importar un archivo de TEXTO PLANO con hashes objetivo,
    uno por linea, en cualquiera de estos formatos:

        <hash>
        <usuario_id>:<hash>

    El algoritmo se AUTODETECTA por la longitud hexadecimal de cada hash
    (32=MD5, 64=SHA-256, 128=SHA-512) mediante
    `hash_engine.detectar_algoritmo_por_longitud`. Si no se indica
    usuario_id, se asigna uno secuencial ("usuario_001", "usuario_002", ...).
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro el archivo de hashes objetivo: {ruta}")
    lineas = [l.strip() for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lineas:
        raise ValueError(f"El archivo de hashes objetivo '{ruta}' esta vacio.")

    objetivos: List[RegistroObjetivo] = []
    for i, linea in enumerate(lineas, start=1):
        if linea.startswith("#"):
            continue
        if ":" in linea:
            usuario_id, h = linea.split(":", 1)
            usuario_id = usuario_id.strip()
        else:
            usuario_id, h = f"usuario_{i:03d}", linea
        h = h.strip().lower()
        algoritmo = detectar_algoritmo_por_longitud(h)
        objetivos.append(RegistroObjetivo(usuario_id, h, algoritmo))

    if not objetivos:
        # `lineas` no estaba vacio (ya se valido arriba), pero si el
        # archivo contenia UNICAMENTE comentarios ("# ..."), `objetivos`
        # puede terminar vacio sin que se detecte. A diferencia de
        # `cargar_objetivos_csv` (que ya fallaba en este caso), esta rama
        # no lanzaba error: se corrige para que ambos loaders sean
        # consistentes (docs/ANALISIS_PROYECTO.md).
        raise ValueError(
            f"El archivo de hashes objetivo '{ruta}' no contiene ningun hash valido "
            "(solo comentarios o lineas vacias)."
        )
    return objetivos


def cargar_objetivos(ruta: str | Path) -> List[RegistroObjetivo]:
    """
    Punto de entrada unico para RF-01: elige el parser segun la extension
    del archivo (`.csv` -> `cargar_objetivos_csv`, cualquier otra cosa,
    tipicamente `.txt` -> `cargar_objetivos_texto` con autodeteccion).
    """
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".csv":
        return cargar_objetivos_csv(ruta)
    return cargar_objetivos_texto(ruta)


def validar_algoritmo_coincide(objetivos: List[RegistroObjetivo], algoritmo_cli: str) -> None:
    """
    Verifica que el algoritmo pedido por el usuario en la CLI (`--algoritmo`)
    coincida con el de los objetivos cargados, para fallar con un mensaje
    claro en vez de ejecutar una auditoria completa que recupere 0/N
    credenciales por un simple desajuste de algoritmo.
    """
    algoritmo_cli = normalizar_algoritmo(algoritmo_cli)
    declarados = {obj.algoritmo for obj in objetivos}
    if declarados and declarados != {algoritmo_cli}:
        raise ValueError(
            f"--algoritmo {algoritmo_cli} no coincide con el algoritmo de los hashes "
            f"cargados ({', '.join(sorted(declarados))}). Usa --algoritmo "
            f"{sorted(declarados)[0]} o vuelve a generar el dataset con "
            f"--algoritmo {algoritmo_cli}."
        )
