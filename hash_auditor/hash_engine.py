"""
hash_engine.py
--------------
Motor criptografico multi-algoritmo. Unico punto del sistema que sabe como
calcular un resumen (hash) de una contraseña en texto plano.

Soporta MD5, SHA-256 y SHA-512 (RF-07). Usa unicamente `hashlib` (RNF-01).

NOTA DE SEGURIDAD / USO EDUCATIVO
----------------------------------
Este modulo se utiliza exclusivamente para auditar, con datos sinteticos
generados por el propio sistema (ver dataset_generator.py), la robustez de
contraseñas frente a un ataque de diccionario clasico. No se usa contra
sistemas, cuentas o bases de datos reales de terceros.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict

# Tabla de algoritmos soportados -> constructor de hashlib
_ALGORITHMS: Dict[str, Callable[[], "hashlib._Hash"]] = {
    "md5": hashlib.md5,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


def algoritmos_soportados() -> list[str]:
    """Devuelve la lista de algoritmos de hash soportados por el sistema."""
    return sorted(_ALGORITHMS.keys())


def normalizar_algoritmo(algoritmo: str) -> str:
    """Valida y normaliza el nombre de un algoritmo (acepta mayus/minus, guiones)."""
    clave = algoritmo.strip().lower().replace("-", "").replace("_", "")
    if clave not in _ALGORITHMS:
        soportados = ", ".join(algoritmos_soportados())
        raise ValueError(
            f"Algoritmo '{algoritmo}' no soportado. Algoritmos disponibles: {soportados}"
        )
    return clave


def calcular_hash(password: str, algoritmo: str) -> str:
    """
    Calcula el resumen criptografico hexadecimal de `password` usando
    `algoritmo` ('md5' | 'sha256' | 'sha512').

    Uso puntual / conveniencia. Para bucles de alto volumen (auditoria
    secuencial o cada trabajador paralelo) usar `obtener_constructor` y
    llamar al constructor directamente: evita volver a validar/normalizar
    el nombre del algoritmo en CADA candidato, lo que en bucles de
    millones de iteraciones es una diferencia de rendimiento medible.
    """
    clave = normalizar_algoritmo(algoritmo)
    constructor = _ALGORITHMS[clave]
    return constructor(password.encode("utf-8")).hexdigest()


def obtener_constructor(algoritmo: str) -> Callable[[bytes], "hashlib._Hash"]:
    """
    Devuelve el constructor de hashlib (ej. hashlib.sha256) ya resuelto,
    para usar en el "hot loop" de los motores de auditoria:

        hash_fn = obtener_constructor(algoritmo)
        digest = hash_fn(candidato.encode("utf-8")).hexdigest()
    """
    clave = normalizar_algoritmo(algoritmo)
    return _ALGORITHMS[clave]


def tamano_hash_hex(algoritmo: str) -> int:
    """Longitud en caracteres hexadecimales del hash para el algoritmo dado."""
    clave = normalizar_algoritmo(algoritmo)
    return _LONGITUD_A_ALGORITMO_INV[clave]


_LONGITUD_A_ALGORITMO_INV = {"md5": 32, "sha256": 64, "sha512": 128}
_LONGITUD_A_ALGORITMO = {32: "md5", 64: "sha256", 128: "sha512"}


def detectar_algoritmo_por_longitud(hash_hex: str) -> str:
    """
    Autodetecta el algoritmo de hash a partir de la longitud hexadecimal
    del resumen (RF-07): 32 caracteres -> MD5, 64 -> SHA-256, 128 -> SHA-512.

    Se usa tanto para importar archivos de texto plano sin columna de
    algoritmo (RF-01) como para VALIDAR que el algoritmo declarado por el
    usuario (`--algoritmo`) coincide con los hashes realmente cargados,
    evitando el escenario silencioso de "0 descifrados" cuando hay un
    desajuste (p. ej. cargar hashes SHA-256 y auditar con `--algoritmo md5`).
    """
    limpio = hash_hex.strip().lower()
    if not limpio or any(c not in "0123456789abcdef" for c in limpio):
        raise ValueError(f"'{hash_hex}' no parece un hash hexadecimal valido.")
    algoritmo = _LONGITUD_A_ALGORITMO.get(len(limpio))
    if algoritmo is None:
        soportadas = ", ".join(str(n) for n in sorted(_LONGITUD_A_ALGORITMO))
        raise ValueError(
            f"No se pudo autodetectar el algoritmo: el hash '{hash_hex[:16]}...' "
            f"tiene {len(limpio)} caracteres hexadecimales (longitudes soportadas: {soportadas})."
        )
    return algoritmo
