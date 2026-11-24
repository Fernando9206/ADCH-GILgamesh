"""
parallel_auditor.py
---------------------
Auditor en modo PARALELO mediante `multiprocessing` (RF-05, RF-06).

Arquitectura (ver tambien docs/ARQUITECTURA.md):

    Proceso Productor                         Procesos Trabajadores (1..N)
    ------------------                         -----------------------------
    lee diccionario base                       mientras no haya señal de parada:
    empaqueta PALABRAS BASE en lotes               toma un LOTE DE PALABRAS
    pequeños (NO expande mutaciones)               para cada palabra del lote:
    los deposita en `task_queue`  ---Queue--->         expande sus mutaciones
    (cola ACOTADA: si se llena,                        LOCALMENTE (mutar_palabra)
     el productor espera -> controla                   calcula el hash de cada
     el uso de memoria RAM)                             candidato
    al terminar, envia un "poison                      compara contra hashes objetivo
     pill" (None) por trabajador                   si hay coincidencia:
                                                        escribe en bitacora compartida
                                                        bajo Lock (exclusion mutua)
                                                        envia hallazgo a `result_queue`
                                                    incrementa contador global (Lock)

    Proceso Principal (colector)
    ----------------------------
    lee `result_queue` en tiempo real y muestra progreso (RNF-04)
    DEDUPLICA cada hallazgo por (hash, usuario_id) antes de contarlo
    cuando se recuperan TODAS las cuentas objetivo:
        activa `stop_event` (Event) -> señal de parada global (RF-10)
    espera (join) a productor y trabajadores; si alguno no responde en el
        tiempo de gracia, lo termina explicitamente (RNF-03, sin deadlocks)

IMPORTANTE -- por que el productor NUNCA expande mutaciones
-------------------------------------------------------------
Una version anterior de este modulo hacia que el Productor generara TODOS
los candidatos mutados (millones de strings) y los serializara (pickle) en
lotes hacia la cola. Eso convertia al Productor -un unico proceso- en un
cuello de botella serial: segun la Ley de Amdahl, si esa fraccion serial
domina ~80% del tiempo total, el Speedup maximo posible (con infinitos
nucleos) queda limitado a 1/0.80 = 1.25x, sin importar cuantos trabajadores
se agreguen (esto es exactamente lo que se observaba: ~1.19x con 4-8
workers). La solucion es enviar por la cola solo las PALABRAS BASE (unos
pocos bytes cada una); cada trabajador expande sus propias mutaciones en
paralelo con los demas, de modo que el trabajo CPU-bound (generar strings +
hashear) se reparte realmente entre los N procesos.

Tecnicas de la materia demostradas explicitamente:
  - Paralelismo real con procesos (evita el GIL de Python) -> RF-05/RF-06
  - Comunicacion entre procesos via `multiprocessing.Queue`  -> RF-08
  - Exclusion mutua via `multiprocessing.Lock`                -> RF-09
  - Señalizacion / parada temprana via `multiprocessing.Event` -> RF-10
"""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_module
import time
from pathlib import Path
from typing import Dict, List, Sequence

from .dictionary import DEFAULT_TAM_LOTE_PALABRAS, generar_lotes_palabras, mutar_palabra
from .hash_engine import obtener_constructor
from .sequential_auditor import Hallazgo, ResultadoAuditoria, construir_mapa_objetivos, contar_cuentas

QUEUE_MAXSIZE = 200         # lotes de PALABRAS en vuelo como maximo (cada lote es minusculo)
POLL_TIMEOUT_SEG = 0.2      # timeout de Queue.get para poder revisar stop_event
JOIN_GRACE_SEG = 2.0        # tiempo de gracia antes de forzar terminate()


# ---------------------------------------------------------------------------
# Proceso PRODUCTOR
# ---------------------------------------------------------------------------
def _proceso_productor(
    palabras: Sequence[str],
    tam_lote_palabras: int,
    task_queue: "mp.Queue",
    num_trabajadores: int,
    stop_event,
) -> None:
    """Genera lotes de PALABRAS BASE (no de candidatos) y los encola."""
    try:
        for lote in generar_lotes_palabras(palabras, tam_lote_palabras):
            if stop_event.is_set():
                break
            # task_queue.put bloquea si la cola esta llena: esto ES el
            # mecanismo que acota el uso de memoria del pipeline (RNF-03).
            while True:
                if stop_event.is_set():
                    return
                try:
                    task_queue.put(lote, timeout=POLL_TIMEOUT_SEG)
                    break
                except queue_module.Full:
                    continue
    finally:
        # "poison pill": una señal de fin por cada trabajador activo.
        #
        # IMPORTANTE: se reintenta hasta que la cola tenga espacio, SIN
        # abandonar en el primer timeout. Una version anterior hacia
        # `except Full: pass` (se rendia tras 1s si la cola seguia llena),
        # lo que con diccionarios grandes (cola llena por mas de 1s) podia
        # dejar a un trabajador sin su señal de fin: ese trabajador queda
        # entonces sondeando una cola vacia para siempre (ni stop_event
        # se activa, porque la auditoria termino por agotar el espacio de
        # busqueda, no por descifrar el 100%), y el colector nunca ve a
        # todos los procesos terminar -> livelock (docs/ANALISIS_PROYECTO.md).
        # Como el Productor ya generó todo el trabajo, los trabajadores
        # siguen activos consumiendo la cola, por lo que siempre se libera
        # espacio: este bucle no puede quedarse esperando indefinidamente
        # salvo que un trabajador haya muerto de forma anormal, caso que
        # igualmente se resuelve con terminate()/join() en el `finally`
        # de `auditar_paralelo`.
        for _ in range(num_trabajadores):
            while True:
                if stop_event.is_set():
                    # Los trabajadores ya estan saliendo (o salieron) por la
                    # señal de parada temprana (RF-10): no dependen del
                    # poison pill para terminar, asi que no forzamos la
                    # entrega (evita esperar para siempre si la cola sigue
                    # llena y ya nadie la esta consumiendo). Se intenta una
                    # vez mas "best effort" y se continua con el siguiente.
                    try:
                        task_queue.put_nowait(None)
                    except queue_module.Full:
                        pass
                    break
                try:
                    task_queue.put(None, timeout=POLL_TIMEOUT_SEG)
                    break
                except queue_module.Full:
                    continue


# ---------------------------------------------------------------------------
# Proceso TRABAJADOR (consumidor)
# ---------------------------------------------------------------------------
def _proceso_trabajador(
    worker_id: int,
    task_queue: "mp.Queue",
    result_queue: "mp.Queue",
    stop_event,
    objetivos_hash_a_usuarios: Dict[str, List[str]],
    algoritmo: str,
    incluir_extendido: bool,
    bitacora_path: str,
    bitacora_lock,
    contador,
    contador_lock,
    tiempo_inicio: float,
) -> None:
    """
    Consume lotes de PALABRAS BASE, expande sus mutaciones LOCALMENTE,
    calcula hashes y reporta hallazgos. Este es el cambio arquitectonico
    clave frente a una version anterior que recibia candidatos ya
    expandidos (ver docstring del modulo).
    """
    nombre_trabajador = f"worker-{worker_id}"
    # Se resuelve el constructor de hashlib UNA sola vez por proceso en vez
    # de validar/normalizar el algoritmo en cada candidato (hot loop).
    hash_fn = obtener_constructor(algoritmo)

    while True:
        if stop_event.is_set():
            break
        try:
            lote_palabras = task_queue.get(timeout=POLL_TIMEOUT_SEG)
        except queue_module.Empty:
            continue

        if lote_palabras is None:
            break  # poison pill: no hay mas trabajo pendiente

        evaluados_en_lote = 0
        for palabra in lote_palabras:
            if stop_event.is_set():
                break
            # NOTA DE RENDIMIENTO: `stop_event.is_set()` se revisa por
            # PALABRA (unas pocas veces por lote), nunca por candidato
            # individual dentro del bucle interno de abajo. `Event.is_set()`
            # usa primitivas de sincronizacion del sistema operativo, y
            # llamarla por cada uno de los millones de candidatos introduce
            # un overhead de IPC muchas veces mayor que el propio calculo
            # del hash, invirtiendo por completo la ganancia del paralelismo.
            for candidato in mutar_palabra(palabra, incluir_extendido):
                evaluados_en_lote += 1
                h = hash_fn(candidato.encode("utf-8")).hexdigest()
                usuarios = objetivos_hash_a_usuarios.get(h)
                if usuarios:
                    tiempo_relativo = time.time() - tiempo_inicio
                    for usuario_id in usuarios:
                        # RF-09: exclusion mutua al escribir en el recurso
                        # compartido (bitacora en disco), evitando
                        # condiciones de carrera cuando dos trabajadores
                        # descubren credenciales simultaneamente.
                        with bitacora_lock:
                            with open(bitacora_path, "a", encoding="utf-8") as f:
                                f.write(f"{usuario_id},{candidato},{h},{nombre_trabajador},{tiempo_relativo:.6f}\n")
                        # RF-08: comunicacion en tiempo real hacia el colector.
                        result_queue.put((usuario_id, candidato, h, nombre_trabajador, tiempo_relativo))

        # Incremento del contador global de hashes evaluados (throughput).
        # Se actualiza una vez por LOTE (no por candidato) para reducir la
        # contencion sobre el Lock sin perder precision relevante.
        with contador_lock:
            contador.value += evaluados_en_lote


# ---------------------------------------------------------------------------
# Orquestacion (proceso principal)
# ---------------------------------------------------------------------------
def auditar_paralelo(
    palabras: Sequence[str],
    objetivos: Sequence,
    algoritmo: str,
    num_trabajadores: int,
    incluir_extendido: bool = False,
    tam_lote_palabras: int = DEFAULT_TAM_LOTE_PALABRAS,
    bitacora_path: str | Path = "results/bitacora_compartida.log",
    on_hallazgo=None,
    **kwargs,
) -> ResultadoAuditoria:
    """
    Ejecuta la auditoria repartiendo el trabajo entre `num_trabajadores`
    procesos independientes (RF-05).

    `on_hallazgo(usuario_id, password, worker, tiempo)` es un callback
    opcional invocado en tiempo real por cada hallazgo (RNF-04), util para
    imprimir progreso en consola desde quien llama a esta funcion.
    """
    if num_trabajadores < 1:
        raise ValueError("num_trabajadores debe ser >= 1")
    # Compatibilidad retroactiva: versiones previas de la CLI usaban el
    # nombre de parametro `batch_size` (candidatos por lote). Se acepta
    # como alias de `tam_lote_palabras` para no romper scripts existentes,
    # aunque su significado ahora es "palabras base por lote".
    if "batch_size" in kwargs:
        tam_lote_palabras = kwargs.pop("batch_size")
    if kwargs:
        raise TypeError(f"Argumentos no reconocidos: {list(kwargs)}")

    objetivos_hash_a_usuarios = construir_mapa_objetivos(objetivos)
    total_objetivos = contar_cuentas(objetivos_hash_a_usuarios)

    bitacora_path = Path(bitacora_path)
    bitacora_path.parent.mkdir(parents=True, exist_ok=True)
    bitacora_path.write_text("", encoding="utf-8")  # limpiar bitacora previa

    ctx = mp.get_context()  # 'spawn' en Windows, 'fork'/'spawn' en otros SO
    task_queue = ctx.Queue(maxsize=QUEUE_MAXSIZE)
    result_queue = ctx.Queue()
    stop_event = ctx.Event()
    contador = ctx.Value("q", 0)       # 'q' = long long, contador de hashes evaluados
    contador_lock = ctx.Lock()
    bitacora_lock = ctx.Lock()

    tiempo_inicio = time.time()
    inicio_perf = time.perf_counter()

    productor = ctx.Process(
        target=_proceso_productor,
        name="productor",
        args=(palabras, tam_lote_palabras, task_queue, num_trabajadores, stop_event),
    )
    trabajadores = [
        ctx.Process(
            target=_proceso_trabajador,
            name=f"worker-{i}",
            args=(
                i, task_queue, result_queue, stop_event,
                objetivos_hash_a_usuarios, algoritmo, incluir_extendido,
                str(bitacora_path), bitacora_lock,
                contador, contador_lock, tiempo_inicio,
            ),
        )
        for i in range(1, num_trabajadores + 1)
    ]

    productor.start()
    for t in trabajadores:
        t.start()

    hallazgos: List[Hallazgo] = []
    # RNF-02 / corrige bug 3.3 del analisis: si el diccionario base tiene
    # palabras duplicadas, dos lotes distintos pueden generar el MISMO
    # candidato y, por lo tanto, el mismo hallazgo mas de una vez. Se
    # deduplica por (hash, usuario_id) antes de contarlo, para no inflar
    # `len(hallazgos)` ni disparar `stop_event` antes de tiempo.
    ya_registrados: set[tuple[str, str]] = set()
    try:
        while len(hallazgos) < total_objetivos:
            try:
                usuario_id, password, h, worker, tiempo_rel = result_queue.get(timeout=POLL_TIMEOUT_SEG)
            except queue_module.Empty:
                # ¿Ya no queda nadie trabajando? (todos los procesos terminaron
                # sin que se completara el 100% -> se agoto el espacio de busqueda)
                if not productor.is_alive() and all(not t.is_alive() for t in trabajadores):
                    break
                continue

            clave = (h, usuario_id)
            if clave in ya_registrados:
                continue  # hallazgo duplicado (palabra repetida en el diccionario)
            ya_registrados.add(clave)

            hallazgo = Hallazgo(
                usuario_id=usuario_id,
                password=password,
                hash=h,
                trabajador=worker,
                tiempo_hallazgo_seg=tiempo_rel,
            )
            hallazgos.append(hallazgo)
            if on_hallazgo is not None:
                on_hallazgo(usuario_id, password, worker, tiempo_rel)

        # RF-10: señal de parada global en cuanto se cumple la condicion de
        # termino (100% descifrado, o se agoto el espacio de busqueda).
        stop_event.set()
    finally:
        stop_event.set()
        productor.join(timeout=JOIN_GRACE_SEG)
        for t in trabajadores:
            t.join(timeout=JOIN_GRACE_SEG)
        # RNF-03: liberacion limpia de cualquier proceso que no respondiera.
        for p in [productor, *trabajadores]:
            if p.is_alive():
                p.terminate()
                p.join(timeout=JOIN_GRACE_SEG)

        # Drenar cualquier hallazgo residual que haya quedado en la cola
        # (puede ocurrir si varios workers reportan justo antes del stop).
        while True:
            try:
                usuario_id, password, h, worker, tiempo_rel = result_queue.get_nowait()
            except queue_module.Empty:
                break
            clave = (h, usuario_id)
            if clave not in ya_registrados:
                ya_registrados.add(clave)
                hallazgos.append(Hallazgo(usuario_id, password, h, worker, tiempo_rel))

        task_queue.close()
        result_queue.close()

    tiempo_total = time.perf_counter() - inicio_perf
    candidatos_evaluados = contador.value

    hallazgos.sort(key=lambda hz: hz.tiempo_hallazgo_seg)

    return ResultadoAuditoria(
        modo="procesos",
        num_trabajadores=num_trabajadores,
        algoritmo=algoritmo,
        total_objetivos=total_objetivos,
        hallazgos=hallazgos,
        candidatos_evaluados=candidatos_evaluados,
        tiempo_total_seg=tiempo_total,
    )
