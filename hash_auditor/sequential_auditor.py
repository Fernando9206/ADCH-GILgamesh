"""
sequential_auditor.py
----------------------
Auditor en modo SECUENCIAL: linea base (baseline) para el calculo de
metricas de aceleracion (Speedup) y eficiencia paralela (RF-04).

Un unico hilo recorre, uno por uno, todos los candidatos generados por el
motor de mutaciones (hash_auditor.dictionary), calcula su hash y lo compara
contra el diccionario de hashes objetivo. Se detiene en cuanto encuentra
el 100% de las contraseñas (early stopping, igual que la version paralela,
para que la comparacion de tiempos sea justa) o al agotar el espacio de
busqueda.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Sequence

from .hash_engine import obtener_constructor
from .dictionary import generar_candidatos


def construir_mapa_objetivos(objetivos: Sequence) -> Dict[str, List[str]]:
    """
    Construye el mapa `hash -> [usuario_id, ...]` usado por los tres
    motores de auditoria para buscar coincidencias en O(1).

    Se usa una LISTA de usuarios por hash (en vez de un solo usuario_id)
    para soportar correctamente el caso, frecuente en fugas reales, de
    que DOS usuarios distintos compartan la misma contraseña (y por lo
    tanto el mismo hash). Con un mapa `hash -> usuario_id` simple, el
    segundo usuario sobrescribiria silenciosamente al primero y jamas
    aparecería en el reporte de vulnerabilidad (RNF-02: ningun hallazgo
    debe perderse).
    """
    mapa: Dict[str, List[str]] = {}
    for obj in objetivos:
        mapa.setdefault(obj.hash, []).append(obj.usuario_id)
    return mapa


def contar_cuentas(mapa: Dict[str, List[str]]) -> int:
    """Numero total de CUENTAS de usuario (no de hashes unicos) a auditar."""
    return sum(len(usuarios) for usuarios in mapa.values())


@dataclass
class Hallazgo:
    usuario_id: str
    password: str
    hash: str
    trabajador: str
    tiempo_hallazgo_seg: float


@dataclass
class ResultadoAuditoria:
    modo: str
    num_trabajadores: int
    algoritmo: str
    total_objetivos: int
    hallazgos: List[Hallazgo]
    candidatos_evaluados: int
    tiempo_total_seg: float

    @property
    def descifrados(self) -> int:
        return len(self.hallazgos)

    @property
    def throughput_hashes_seg(self) -> float:
        if self.tiempo_total_seg <= 0:
            return float(self.candidatos_evaluados)
        return self.candidatos_evaluados / self.tiempo_total_seg


def auditar_secuencial(
    palabras: Sequence[str],
    objetivos: Sequence,
    algoritmo: str,
    incluir_extendido: bool = False,
) -> ResultadoAuditoria:
    """
    Ejecuta la auditoria en modo 100% secuencial (RF-04).

    `objetivos` es una lista de registros con atributos `.usuario_id` y
    `.hash` (ver dataset_generator.RegistroObjetivo o equivalentes cargados
    desde CSV).
    """
    # Mapa hash -> [usuario_id, ...] para busqueda O(1) por candidato,
    # igual que hace cada trabajador en los motores concurrentes, y sin
    # perder usuarios que comparten la misma contraseña.
    pendientes = construir_mapa_objetivos(objetivos)
    total_objetivos = contar_cuentas(pendientes)
    hash_fn = obtener_constructor(algoritmo)

    hallazgos: List[Hallazgo] = []
    candidatos_evaluados = 0
    inicio = time.perf_counter()

    for candidato in generar_candidatos(palabras, incluir_extendido):
        candidatos_evaluados += 1
        h = hash_fn(candidato.encode("utf-8")).hexdigest()
        if h in pendientes:
            tiempo_rel = time.perf_counter() - inicio
            for usuario_id in pendientes.pop(h):
                hallazgos.append(
                    Hallazgo(
                        usuario_id=usuario_id,
                        password=candidato,
                        hash=h,
                        trabajador="secuencial",
                        tiempo_hallazgo_seg=tiempo_rel,
                    )
                )
            if not pendientes:
                break  # early stopping: ya se recuperaron todas las contraseñas

    tiempo_total = time.perf_counter() - inicio

    return ResultadoAuditoria(
        modo="secuencial",
        num_trabajadores=1,
        algoritmo=algoritmo,
        total_objetivos=total_objetivos,
        hallazgos=hallazgos,
        candidatos_evaluados=candidatos_evaluados,
        tiempo_total_seg=tiempo_total,
    )
