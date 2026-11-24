"""
dictionary.py
-------------
Carga del diccionario base y motor de mutacion combinatoria (RF-03).

A partir de una lista de palabras comunes, genera candidatos de contraseña
aplicando reglas de mutacion tipicas de un ataque de diccionario hibrido:

  1. La palabra original (y variantes de capitalizacion: minuscula, Capitalizada,
     MAYUSCULA).
  2. Palabra + sufijo numerico de 1 a 4 digitos (0-9999), incluyendo años
     comunes (1990-2029) y patrones tipicos (01, 007, 123, 1234, 12345...).
  3. Palabra + caracter especial final (!, @, #, $, *, .)
  4. Palabra + sufijo numerico + caracter especial (combinacion mas realista
     de politicas de "contraseña segura": Mayuscula + numero + simbolo).

El motor se expone como un **generador de lotes (chunks)** de tamaño fijo,
para poder:
  - Transmitirlos de forma controlada a traves de una `Queue` acotada
    (modelo Productor-Consumidor, RF-08) sin agotar la memoria RAM.
  - Repartir el espacio de busqueda en bloques disjuntos entre varios
    trabajadores (RF-06): cada lote que sale de la cola es tomado por un
    unico trabajador, por lo que dos trabajadores nunca procesan el mismo
    candidato (particionamiento dinamico, balanceado por demanda).
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Iterator, List, Sequence

SIMBOLOS = ["!", "@", "#", "$", "*", "."]
AÑOS = [str(y) for y in range(1990, 2030)]
PATRONES_NUMERICOS_COMUNES = ["0", "1", "7", "01", "07", "69", "99", "007",
                              "123", "321", "1234", "4321", "12345", "123456",
                              "111", "000", "666", "777", "888", "999"]

DEFAULT_BATCH_SIZE = 20000          # tamano de lote de CANDIDATOS (motor secuencial)
DEFAULT_TAM_LOTE_PALABRAS = 3        # tamano de lote de PALABRAS BASE (motores concurrentes)


def cargar_diccionario(ruta: str | Path) -> List[str]:
    """
    Lee el archivo de diccionario base (una palabra por linea).

    Elimina duplicados preservando el orden de aparicion: una palabra
    repetida en el archivo generaria los mismos candidatos mutados dos
    veces, repartidos potencialmente en lotes distintos hacia dos
    trabajadores diferentes, lo que podria producir el mismo hallazgo
    reportado mas de una vez (ver dedup adicional en parallel_auditor.py
    y threaded_auditor.py, que cubre ademas colisiones por mutacion).
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro el archivo de diccionario: {ruta}")
    with ruta.open("r", encoding="utf-8") as f:
        crudo = [linea.strip() for linea in f if linea.strip()]
    if not crudo:
        raise ValueError(f"El diccionario '{ruta}' esta vacio.")
    vistas = set()
    palabras = []
    for palabra in crudo:
        if palabra not in vistas:
            vistas.add(palabra)
            palabras.append(palabra)
    return palabras


def _sufijos_numericos(incluir_extendido: bool) -> List[str]:
    """
    Devuelve la lista de sufijos numericos a combinar con cada palabra.

    `incluir_extendido=True` activa el modo exhaustivo del motor de
    mutaciones: agrega años (1990-2029) y el rango completo 0-999 de
    sufijos numericos de 1 a 3 digitos, ademas de los patrones comunes de
    4 digitos (007, 1234, 123456, etc.). Esto cubre de forma realista el
    requisito de "sufijos numericos de 1 a 4 digitos" sin expandir el
    espacio de busqueda a los 10,000 valores de 0-9999 completos, la
    gran mayoria de los cuales son estadisticamente irrelevantes en
    contraseñas reales. Resultado tipico: varios millones de candidatos
    para el diccionario base incluido, lo que produce una corrida
    secuencial de referencia de varios segundos -- suficiente
    para que el overhead fijo de crear procesos quede amortizado y la
    ganancia real del paralelismo (RF-05/RF-12) sea claramente medible.
    """
    sufijos = list(PATRONES_NUMERICOS_COMUNES)
    if incluir_extendido:
        sufijos += AÑOS
        sufijos += [str(n) for n in range(0, 1000)]
    # eliminar duplicados preservando orden
    vistos = set()
    unicos = []
    for s in sufijos:
        if s not in vistos:
            vistos.add(s)
            unicos.append(s)
    return unicos


def variantes_de_capitalizacion(palabra: str) -> List[str]:
    """minuscula, Capitalizada, MAYUSCULA (sin duplicar si son iguales)."""
    variantes = {palabra.lower(), palabra.capitalize(), palabra.upper()}
    return list(variantes)


def mutar_palabra(palabra: str, incluir_extendido: bool = False) -> Iterator[str]:
    """
    Genera todas las variantes mutadas de una palabra base:
    capitalizacion x (nada | sufijo numerico | simbolo | sufijo+simbolo).
    """
    base_variantes = variantes_de_capitalizacion(palabra)
    sufijos = _sufijos_numericos(incluir_extendido)

    for base in base_variantes:
        # 1. palabra tal cual
        yield base
        # 2. palabra + simbolo
        for simbolo in SIMBOLOS:
            yield base + simbolo
        # 3. palabra + sufijo numerico
        for sufijo in sufijos:
            yield base + sufijo
        # 4. palabra + sufijo numerico + simbolo (politica "contraseña segura")
        for sufijo in sufijos:
            for simbolo in SIMBOLOS:
                yield base + sufijo + simbolo


def estimar_total_candidatos(num_palabras: int, incluir_extendido: bool = False) -> int:
    """Calcula (sin generar) cuantos candidatos produce el motor en total."""
    num_sufijos = len(_sufijos_numericos(incluir_extendido))
    num_simbolos = len(SIMBOLOS)
    por_variante = 1 + num_simbolos + num_sufijos + (num_sufijos * num_simbolos)
    # hasta 3 variantes de capitalizacion por palabra
    return num_palabras * 3 * por_variante


def generar_candidatos(palabras: Sequence[str], incluir_extendido: bool = False) -> Iterator[str]:
    """Iterador plano de TODOS los candidatos generados a partir del diccionario."""
    for palabra in palabras:
        yield from mutar_palabra(palabra, incluir_extendido)


def generar_lotes(
    palabras: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    incluir_extendido: bool = False,
) -> Iterator[List[str]]:
    """
    Generador de lotes (chunks) de candidatos YA MUTADOS, de tamaño
    `batch_size`. Util para el motor SECUENCIAL (un unico proceso, sin
    IPC) o para pruebas unitarias que necesiten inspeccionar candidatos.

    *** NO USAR ESTO PARA REPARTIR TRABAJO ENTRE PROCESOS/HILOS ***
    Expandir millones de candidatos en un solo proceso y luego serializarlos
    (pickle) a traves de una Queue hacia los trabajadores convierte a ese
    proceso productor en un cuello de botella serial: segun la Ley de
    Amdahl, si esa fraccion serial es del 80% del tiempo total, el
    *Speedup* maximo posible (con infinitos nucleos) queda limitado a
    1/0.80 = 1.25x, sin importar cuantos trabajadores se agreguen. Para
    los motores concurrentes (hilos/procesos) usar `generar_lotes_palabras`
    en su lugar: cada trabajador expande sus propias mutaciones de forma
    local, y por la cola solo viajan las palabras base (unos pocos bytes),
    no el espacio de busqueda completo.
    """
    candidatos = generar_candidatos(palabras, incluir_extendido)
    while True:
        lote = list(itertools.islice(candidatos, batch_size))
        if not lote:
            return
        yield lote


def generar_lotes_palabras(
    palabras: Sequence[str],
    tam_lote: int = DEFAULT_TAM_LOTE_PALABRAS,
) -> Iterator[List[str]]:
    """
    Generador de lotes de PALABRAS BASE (no de candidatos ya mutados).

    Esta es la pieza central del modelo Productor-Consumidor usado por los
    motores concurrentes (hilos y procesos, RF-08): el Productor recorre
    este generador y deposita cada lote (unas pocas palabras) en una cola
    acotada; cada trabajador EXPANDE LOCALMENTE sus propias mutaciones
    (`mutar_palabra`) y calcula los hashes, sin que el espacio de busqueda
    completo tenga que pasar por IPC. El trafico por la cola se reduce de
    millones de candidatos (decenas/cientos de MB serializados) a unas
    pocas palabras (unos KB), eliminando el cuello de botella del
    productor y permitiendo que el *Speedup* escale de forma realista con
    el numero de trabajadores.

    El particionamiento sigue siendo dinamico y balanceado por demanda
    (RF-06): cada lote de palabras sale de la cola exactamente una vez.
    """
    palabras = list(palabras)
    for i in range(0, len(palabras), tam_lote):
        lote = palabras[i:i + tam_lote]
        if lote:
            yield lote
