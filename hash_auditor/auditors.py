"""
auditors.py
-----------
Fachada orientada a objetos (RNF-05) sobre los tres motores de auditoria
del sistema. Cada motor concreto (secuencial / hilos / procesos) vive en
su propio modulo como funciones puras y testeables de forma aislada
(sequential_auditor.py, threaded_auditor.py, parallel_auditor.py); las
clases de este modulo son el punto de entrada unico y polimorfico que usa
la CLI (main.py) y que facilita agregar un futuro cuarto motor sin tocar
el codigo que ya funciona (principio abierto/cerrado).

Jerarquia:

    BaseAuditor (ABC)
      ├── AuditorSecuencial   -> sequential_auditor.auditar_secuencial
      ├── AuditorHilos        -> threaded_auditor.auditar_hilos
      └── AuditorProcesos     -> parallel_auditor.auditar_paralelo
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional, Sequence

from .dictionary import DEFAULT_TAM_LOTE_PALABRAS
from .hash_engine import normalizar_algoritmo
from .parallel_auditor import auditar_paralelo
from .sequential_auditor import ResultadoAuditoria, auditar_secuencial
from .threaded_auditor import auditar_hilos

OnHallazgo = Optional[Callable[[str, str, str, float], None]]


class BaseAuditor(ABC):
    """
    Interfaz comun a los tres motores de auditoria.

    Encapsula los parametros de la corrida (diccionario, algoritmo, modo
    exhaustivo) y expone un unico metodo polimorfico `ejecutar(objetivos)`
    que devuelve siempre un `ResultadoAuditoria`, sin importar que motor
    concreto se use por debajo.
    """

    #: Nombre corto del motor, usado en reportes/CLI ("secuencial", "hilos", "procesos")
    nombre_modo: str = "base"

    def __init__(self, palabras: Sequence[str], algoritmo: str, incluir_extendido: bool = False):
        self.palabras = list(palabras)
        self.algoritmo = normalizar_algoritmo(algoritmo)
        self.incluir_extendido = incluir_extendido

    @abstractmethod
    def ejecutar(self, objetivos: Sequence) -> ResultadoAuditoria:
        """Ejecuta la auditoria contra `objetivos` y devuelve el resultado."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - solo para depuracion/logs
        return f"{self.__class__.__name__}(algoritmo={self.algoritmo!r}, extendido={self.incluir_extendido})"


class AuditorSecuencial(BaseAuditor):
    """Linea base: un unico hilo de ejecucion, sin concurrencia (RF-04)."""

    nombre_modo = "secuencial"

    def ejecutar(self, objetivos: Sequence) -> ResultadoAuditoria:
        return auditar_secuencial(self.palabras, objetivos, self.algoritmo, self.incluir_extendido)


class _AuditorConcurrenteBase(BaseAuditor):
    """Campos y comportamiento comunes a los motores concurrentes (hilos/procesos)."""

    def __init__(
        self,
        palabras: Sequence[str],
        algoritmo: str,
        num_trabajadores: int,
        incluir_extendido: bool = False,
        tam_lote_palabras: int = DEFAULT_TAM_LOTE_PALABRAS,
        bitacora_path: str | Path = "results/bitacora.log",
        on_hallazgo: OnHallazgo = None,
    ):
        super().__init__(palabras, algoritmo, incluir_extendido)
        if num_trabajadores < 1:
            raise ValueError("num_trabajadores debe ser >= 1")
        self.num_trabajadores = num_trabajadores
        self.tam_lote_palabras = tam_lote_palabras
        self.bitacora_path = bitacora_path
        self.on_hallazgo = on_hallazgo


class AuditorHilos(_AuditorConcurrenteBase):
    """Motor concurrente con `threading` (RF-05 variante hilos; demuestra el efecto del GIL)."""

    nombre_modo = "hilos"

    def ejecutar(self, objetivos: Sequence) -> ResultadoAuditoria:
        return auditar_hilos(
            self.palabras, objetivos, self.algoritmo, self.num_trabajadores,
            self.incluir_extendido, self.tam_lote_palabras, self.bitacora_path, self.on_hallazgo,
        )


class AuditorProcesos(_AuditorConcurrenteBase):
    """Motor concurrente con `multiprocessing` (RF-05/RF-06..RF-10: paralelismo real)."""

    nombre_modo = "procesos"

    def ejecutar(self, objetivos: Sequence) -> ResultadoAuditoria:
        return auditar_paralelo(
            self.palabras, objetivos, self.algoritmo, self.num_trabajadores,
            self.incluir_extendido, self.tam_lote_palabras, self.bitacora_path, self.on_hallazgo,
        )


#: Registro de motores disponibles por nombre, para construirlos dinamicamente
#: desde la CLI (main.py) sin una cadena larga de if/elif.
MOTORES = {
    "secuencial": AuditorSecuencial,
    "hilos": AuditorHilos,
    "procesos": AuditorProcesos,
}
