"""
threaded_auditor.py
---------------------
Auditor en modo CONCURRENTE POR HILOS (`threading`), paralelo a
`parallel_auditor.py` (que usa `multiprocessing`). Implementa EXACTAMENTE
la misma arquitectura Productor-Consumidor, con las mismas primitivas de
sincronizacion pero en su variante de memoria compartida nativa:

    multiprocessing.Queue  -> queue.Queue
    multiprocessing.Lock   -> threading.Lock
    multiprocessing.Event  -> threading.Event
    multiprocessing.Value  -> entero simple protegido por threading.Lock

Por que existe este modulo (requisito explicito del enunciado: "Hilos y
multihilos")
-----------------------------------------------------------------------
El trabajo de esta auditoria (calcular hashes) es **CPU-bound**. En
CPython, el *Global Interpreter Lock* (GIL) impide que el bytecode de dos
hilos se ejecute realmente en paralelo sobre varios nucleos: aunque
`hashlib` libera el GIL mientras calcula el digest en C, hacerlo para
strings muy cortas (8-20 bytes, como las contraseñas candidatas) tiene un
costo de adquisicion/liberacion del GIL que compite con el propio calculo,
de modo que el *Speedup* real con hilos para ESTE tipo de carga suele ser
muy inferior al de `multiprocessing` (que usa procesos con memoria e
interprete independientes, sin GIL compartido) -- y en bibliotecas puras
en Python puede incluso no haber mejora alguna.

Este modulo permite MEDIR esa diferencia empiricamente (RF-12) comparando
tres filas en la misma tabla de resultados: `secuencial`, `hilos (N)` y
`procesos (N)`. Ver docs/ARQUITECTURA.md §7 para el analisis esperado.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Dict, List, Sequence

from .dictionary import DEFAULT_TAM_LOTE_PALABRAS, generar_lotes_palabras, mutar_palabra
from .hash_engine import obtener_constructor
from .sequential_auditor import Hallazgo, ResultadoAuditoria, construir_mapa_objetivos, contar_cuentas

QUEUE_MAXSIZE = 200
POLL_TIMEOUT_SEG = 0.2
JOIN_GRACE_SEG = 2.0


class _ContadorCompartido:
    """Equivalente simple a `multiprocessing.Value` para hilos (memoria compartida nativa)."""

    def __init__(self) -> None:
        self.valor = 0
        self._lock = threading.Lock()

    def incrementar(self, cantidad: int) -> None:
        with self._lock:
            self.valor += cantidad


def _hilo_productor(
    palabras: Sequence[str],
    tam_lote_palabras: int,
    task_queue: "queue.Queue",
    num_trabajadores: int,
    stop_event: threading.Event,
) -> None:
    """Analogo a `_proceso_productor` de parallel_auditor.py, pero con `threading`."""
    try:
        for lote in generar_lotes_palabras(palabras, tam_lote_palabras):
            if stop_event.is_set():
                break
            while True:
                if stop_event.is_set():
                    return
                try:
                    task_queue.put(lote, timeout=POLL_TIMEOUT_SEG)
                    break
                except queue.Full:
                    continue
    finally:
        # Ver la nota equivalente en parallel_auditor.py: se reintenta
        # entregar el poison pill hasta que haya espacio, en vez de
        # rendirse tras un unico timeout (lo que podia dejar a un hilo
        # esperando para siempre si la cola seguia llena, sin que
        # `stop_event` se hubiera activado -- livelock detectado en
        # docs/ANALISIS_PROYECTO.md). Si `stop_event` SI esta activo, los
        # hilos ya estan saliendo por la señal de parada temprana y no
        # dependen del pill, asi que no se fuerza la entrega.
        for _ in range(num_trabajadores):
            while True:
                if stop_event.is_set():
                    try:
                        task_queue.put_nowait(None)
                    except queue.Full:
                        pass
                    break
                try:
                    task_queue.put(None, timeout=POLL_TIMEOUT_SEG)
                    break
                except queue.Full:
                    continue


def _hilo_trabajador(
    worker_id: int,
    task_queue: "queue.Queue",
    result_queue: "queue.Queue",
    stop_event: threading.Event,
    objetivos_hash_a_usuarios: Dict[str, List[str]],
    algoritmo: str,
    incluir_extendido: bool,
    bitacora_path: str,
    bitacora_lock: threading.Lock,
    contador: _ContadorCompartido,
    tiempo_inicio: float,
) -> None:
    """Analogo a `_proceso_trabajador`, pero ejecutandose como hilo (memoria compartida)."""
    nombre_trabajador = f"hilo-{worker_id}"
    hash_fn = obtener_constructor(algoritmo)

    while True:
        if stop_event.is_set():
            break
        try:
            lote_palabras = task_queue.get(timeout=POLL_TIMEOUT_SEG)
        except queue.Empty:
            continue

        if lote_palabras is None:
            break

        evaluados_en_lote = 0
        for palabra in lote_palabras:
            if stop_event.is_set():
                break
            for candidato in mutar_palabra(palabra, incluir_extendido):
                evaluados_en_lote += 1
                h = hash_fn(candidato.encode("utf-8")).hexdigest()
                usuarios = objetivos_hash_a_usuarios.get(h)
                if usuarios:
                    tiempo_relativo = time.time() - tiempo_inicio
                    for usuario_id in usuarios:
                        with bitacora_lock:
                            with open(bitacora_path, "a", encoding="utf-8") as f:
                                f.write(f"{usuario_id},{candidato},{h},{nombre_trabajador},{tiempo_relativo:.6f}\n")
                        result_queue.put((usuario_id, candidato, h, nombre_trabajador, tiempo_relativo))

        contador.incrementar(evaluados_en_lote)


def auditar_hilos(
    palabras: Sequence[str],
    objetivos: Sequence,
    algoritmo: str,
    num_trabajadores: int,
    incluir_extendido: bool = False,
    tam_lote_palabras: int = DEFAULT_TAM_LOTE_PALABRAS,
    bitacora_path: str | Path = "results/bitacora_hilos.log",
    on_hallazgo=None,
) -> ResultadoAuditoria:
    """
    Ejecuta la auditoria repartiendo el trabajo entre `num_trabajadores`
    HILOS dentro de un unico proceso Python (comparar con `auditar_paralelo`
    en parallel_auditor.py, que usa procesos independientes).
    """
    if num_trabajadores < 1:
        raise ValueError("num_trabajadores debe ser >= 1")

    objetivos_hash_a_usuarios = construir_mapa_objetivos(objetivos)
    total_objetivos = contar_cuentas(objetivos_hash_a_usuarios)

    bitacora_path = Path(bitacora_path)
    bitacora_path.parent.mkdir(parents=True, exist_ok=True)
    bitacora_path.write_text("", encoding="utf-8")

    task_queue: "queue.Queue" = queue.Queue(maxsize=QUEUE_MAXSIZE)
    result_queue: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()
    contador = _ContadorCompartido()
    bitacora_lock = threading.Lock()

    tiempo_inicio = time.time()
    inicio_perf = time.perf_counter()

    productor = threading.Thread(
        target=_hilo_productor,
        name="productor",
        args=(palabras, tam_lote_palabras, task_queue, num_trabajadores, stop_event),
    )
    trabajadores = [
        threading.Thread(
            target=_hilo_trabajador,
            name=f"hilo-{i}",
            args=(
                i, task_queue, result_queue, stop_event,
                objetivos_hash_a_usuarios, algoritmo, incluir_extendido,
                str(bitacora_path), bitacora_lock, contador, tiempo_inicio,
            ),
        )
        for i in range(1, num_trabajadores + 1)
    ]

    productor.start()
    for t in trabajadores:
        t.start()

    hallazgos: List[Hallazgo] = []
    ya_registrados: set[tuple[str, str]] = set()
    try:
        while len(hallazgos) < total_objetivos:
            try:
                usuario_id, password, h, worker, tiempo_rel = result_queue.get(timeout=POLL_TIMEOUT_SEG)
            except queue.Empty:
                if not productor.is_alive() and all(not t.is_alive() for t in trabajadores):
                    break
                continue

            clave = (h, usuario_id)
            if clave in ya_registrados:
                continue
            ya_registrados.add(clave)

            hallazgos.append(Hallazgo(usuario_id, password, h, worker, tiempo_rel))
            if on_hallazgo is not None:
                on_hallazgo(usuario_id, password, worker, tiempo_rel)

        stop_event.set()
    finally:
        stop_event.set()
        productor.join(timeout=JOIN_GRACE_SEG)
        for t in trabajadores:
            t.join(timeout=JOIN_GRACE_SEG)
        # Nota RNF-03: a diferencia de los procesos, un hilo de Python no
        # puede ser "terminado" a la fuerza de forma segura; por eso el
        # diseño depende de que `stop_event` + el poison-pill garanticen
        # que cada hilo termine su propio bucle de forma cooperativa.

        while True:
            try:
                usuario_id, password, h, worker, tiempo_rel = result_queue.get_nowait()
            except queue.Empty:
                break
            clave = (h, usuario_id)
            if clave not in ya_registrados:
                ya_registrados.add(clave)
                hallazgos.append(Hallazgo(usuario_id, password, h, worker, tiempo_rel))

    tiempo_total = time.perf_counter() - inicio_perf
    hallazgos.sort(key=lambda hz: hz.tiempo_hallazgo_seg)

    return ResultadoAuditoria(
        modo="hilos",
        num_trabajadores=num_trabajadores,
        algoritmo=algoritmo,
        total_objetivos=total_objetivos,
        hallazgos=hallazgos,
        candidatos_evaluados=contador.valor,
        tiempo_total_seg=tiempo_total,
    )
