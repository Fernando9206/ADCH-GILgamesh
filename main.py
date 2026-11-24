#!/usr/bin/env python3
"""
main.py
-------
CLI principal del Auditor y Descifrador Concurrente de Contraseñas / Hashes.

Subcomandos:
  generate-dataset   Genera un dataset sintetico de hashes objetivo (RF-02).
  audit               Ejecuta una sola auditoria (secuencial / hilos / procesos).
  benchmark           Ejecuta secuencial + hilos(1,2,4,8) + procesos(1,2,4,8),
                       calcula metricas comparativas, genera el reporte final
                       y las graficas SVG.

Ejemplos (PowerShell, desde la carpeta del proyecto):

  python main.py generate-dataset --n 20 --algoritmo sha256
  python main.py audit --modo procesos --workers 4 --algoritmo sha256
  python main.py audit --modo hilos --workers 4 --algoritmo sha256
  python main.py benchmark --algoritmo sha256 --workers 1 2 4 8 --extendido
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

from hash_auditor.auditors import AuditorHilos, AuditorProcesos, AuditorSecuencial
from hash_auditor.charts import generar_graficas
from hash_auditor.dataset_generator import (
    cargar_objetivos,
    generar_dataset,
    guardar_objetivos_csv,
    guardar_referencia_csv,
    validar_algoritmo_coincide,
)
from hash_auditor.dictionary import DEFAULT_TAM_LOTE_PALABRAS, cargar_diccionario, estimar_total_candidatos
from hash_auditor.hash_engine import algoritmos_soportados, normalizar_algoritmo
from hash_auditor.metrics import construir_tabla_metricas, grafico_ascii_speedup, tabla_como_texto
from hash_auditor.report_generator import (
    exportar_hallazgos_csv,
    exportar_metricas_csv,
    generar_reporte_markdown,
)

RAIZ = Path(__file__).resolve().parent
DICCIONARIO_DEFECTO = RAIZ / "data" / "diccionario_base.txt"
RESULTADOS_DIR = RAIZ / "results"

_ALIAS_MODO = {"paralelo": "procesos"}  # compatibilidad retroactiva con la CLI anterior


def _normalizar_modo(modo: str) -> str:
    return _ALIAS_MODO.get(modo, modo)


def _imprimir_hallazgo_en_vivo(usuario_id, password, trabajador, tiempo_rel):
    print(f"  [+] {tiempo_rel:8.4f}s  {trabajador:<12}  {usuario_id} -> {password}")


def cmd_generate_dataset(args: argparse.Namespace) -> None:
    algoritmo = normalizar_algoritmo(args.algoritmo)
    print(f"Generando dataset sintetico: n={args.n}, algoritmo={algoritmo}, seed={args.seed}")
    objetivos, referencia = generar_dataset(
        n=args.n,
        algoritmo=algoritmo,
        diccionario_path=args.diccionario,
        seed=args.seed,
    )
    ruta_objetivos = Path(args.salida)
    ruta_referencia = RESULTADOS_DIR / "referencia_verificacion.csv"
    guardar_objetivos_csv(objetivos, ruta_objetivos)
    guardar_referencia_csv(referencia, ruta_referencia)

    print(f"OK -> {len(objetivos)} hashes objetivo guardados en: {ruta_objetivos}")
    print(f"     (referencia de verificacion, SOLO para el equipo: {ruta_referencia})")
    niveles = {}
    for r in referencia:
        niveles[r.nivel] = niveles.get(r.nivel, 0) + 1
    print(f"     Distribucion por nivel de complejidad: {niveles}")


def _cargar_objetivos(args: argparse.Namespace):
    """
    Carga los objetivos desde --objetivos (CSV o TXT, RF-01/RF-07) o, si no
    se especifico, genera un dataset nuevo en memoria. Valida SIEMPRE que
    el algoritmo pedido coincida con el de los hashes cargados, en vez de
    dejar que la auditoria corra y recupere 0/N credenciales en silencio
    (bug detectado en docs/ANALISIS_PROYECTO.md §3.5).
    """
    algoritmo = normalizar_algoritmo(args.algoritmo)
    if args.objetivos:
        objetivos = cargar_objetivos(args.objetivos)
        validar_algoritmo_coincide(objetivos, algoritmo)
        return objetivos

    print("No se especifico --objetivos: generando un dataset nuevo en memoria...")
    objetivos, referencia = generar_dataset(
        n=args.n, algoritmo=algoritmo,
        diccionario_path=args.diccionario, seed=args.seed,
    )
    guardar_referencia_csv(referencia, RESULTADOS_DIR / "referencia_verificacion.csv")
    return objetivos


def _construir_auditor(modo: str, palabras, algoritmo: str, workers: int, extendido: bool,
                        tam_lote: int, bitacora_path, on_hallazgo=None):
    modo = _normalizar_modo(modo)
    if modo == "secuencial":
        return AuditorSecuencial(palabras, algoritmo, extendido)
    if modo == "hilos":
        return AuditorHilos(palabras, algoritmo, workers, extendido, tam_lote, bitacora_path, on_hallazgo)
    if modo == "procesos":
        return AuditorProcesos(palabras, algoritmo, workers, extendido, tam_lote, bitacora_path, on_hallazgo)
    raise ValueError(f"Modo desconocido: {modo}")


def cmd_audit(args: argparse.Namespace) -> None:
    algoritmo = normalizar_algoritmo(args.algoritmo)
    palabras = cargar_diccionario(args.diccionario)
    objetivos = _cargar_objetivos(args)
    print(f"Espacio de busqueda estimado: {estimar_total_candidatos(len(palabras), args.extendido):,} candidatos")
    print(f"Objetivos a auditar: {len(objetivos)} cuentas (algoritmo={algoritmo})")

    modo = _normalizar_modo(args.modo)
    bitacora_path = RESULTADOS_DIR / f"bitacora_{modo}.log"
    callback = _imprimir_hallazgo_en_vivo if modo != "secuencial" else None
    etiqueta = "SECUENCIAL (baseline)" if modo == "secuencial" else f"{modo.upper()} (workers={args.workers})"
    print(f"\n--- Ejecutando auditoria {etiqueta} ---")

    auditor = _construir_auditor(
        modo, palabras, algoritmo, args.workers, args.extendido,
        args.batch_size, bitacora_path, callback,
    )
    resultado = auditor.ejecutar(objetivos)

    print(f"\nTiempo total: {resultado.tiempo_total_seg:.4f} s")
    print(f"Candidatos evaluados: {resultado.candidatos_evaluados:,}")
    print(f"Descifrados: {resultado.descifrados}/{resultado.total_objetivos}")
    print(f"Throughput: {resultado.throughput_hashes_seg:,.1f} hashes/s")

    exportar_hallazgos_csv(resultado, RESULTADOS_DIR / f"hallazgos_{resultado.modo}.csv")
    print(f"\nHallazgos exportados a: results/hallazgos_{resultado.modo}.csv")


def cmd_benchmark(args: argparse.Namespace) -> None:
    algoritmo = normalizar_algoritmo(args.algoritmo)
    palabras = cargar_diccionario(args.diccionario)
    objetivos = _cargar_objetivos(args)

    total_candidatos = estimar_total_candidatos(len(palabras), args.extendido)
    print("=" * 70)
    print("BENCHMARK: Auditor Concurrente de Contraseñas / Hashes")
    print("=" * 70)
    print(f"Algoritmo: {algoritmo.upper()} | Objetivos: {len(objetivos)} cuentas | "
          f"Espacio de busqueda: {total_candidatos:,} candidatos")

    print("\n[1/3] Ejecutando linea base SECUENCIAL...")
    auditor_sec = AuditorSecuencial(palabras, algoritmo, args.extendido)
    resultado_sec = auditor_sec.ejecutar(objetivos)
    print(f"      -> {resultado_sec.tiempo_total_seg:.4f}s | "
          f"{resultado_sec.descifrados}/{resultado_sec.total_objetivos} descifrados")

    resultados = [resultado_sec]

    if not args.sin_hilos:
        print(f"\n[2/3] Ejecutando versiones con HILOS (threading): {args.workers}")
        for n in args.workers:
            print(f"      Hilos={n} ...", end=" ", flush=True)
            auditor = AuditorHilos(palabras, algoritmo, n, args.extendido, args.batch_size,
                                    RESULTADOS_DIR / f"bitacora_hilos_w{n}.log")
            resultado = auditor.ejecutar(objetivos)
            resultados.append(resultado)
            print(f"{resultado.tiempo_total_seg:.4f}s | "
                  f"{resultado.descifrados}/{resultado.total_objetivos} descifrados")
    else:
        print("\n[2/3] (omitido con --sin-hilos)")

    print(f"\n[3/3] Ejecutando versiones con PROCESOS (multiprocessing): {args.workers}")
    for n in args.workers:
        print(f"      Procesos={n} ...", end=" ", flush=True)
        auditor = AuditorProcesos(palabras, algoritmo, n, args.extendido, args.batch_size,
                                   RESULTADOS_DIR / f"bitacora_procesos_w{n}.log")
        resultado = auditor.ejecutar(objetivos)
        resultados.append(resultado)
        print(f"{resultado.tiempo_total_seg:.4f}s | "
              f"{resultado.descifrados}/{resultado.total_objetivos} descifrados")

    filas = construir_tabla_metricas(resultados)

    print("\n" + tabla_como_texto(filas))
    print()
    print(grafico_ascii_speedup(filas))

    if "hilos" in {r.modo for r in resultados} and len(args.workers) > 0:
        fila_hilos_max = max((f for f in filas if "hilos" in f.etiqueta), key=lambda f: f.num_trabajadores, default=None)
        fila_procesos_max = max((f for f in filas if "procesos" in f.etiqueta), key=lambda f: f.num_trabajadores, default=None)
        if fila_hilos_max and fila_procesos_max:
            print(f"\nComparacion GIL: con N={fila_hilos_max.num_trabajadores}, "
                  f"hilos alcanza {fila_hilos_max.speedup:.2f}x vs. procesos {fila_procesos_max.speedup:.2f}x "
                  f"-> el GIL limita el paralelismo real de 'threading' para esta carga CPU-bound.")

    # Se elige, entre las corridas de PROCESOS (las mas representativas,
    # ya que exploran el espacio completo sin la limitacion del GIL), la
    # que uso MAS trabajadores como referencia de credenciales para el
    # reporte. Antes, `max()` devolvia el primer empate (siempre N=1),
    # atribuyendo todos los hallazgos a un unico worker (bug corregido,
    # ver docs/ANALISIS_PROYECTO.md §3.1).
    candidatos_reporte = [r for r in resultados if r.modo == "procesos"]
    mejor_resultado = max(candidatos_reporte, key=lambda r: (r.descifrados, r.num_trabajadores))

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    generar_reporte_markdown(mejor_resultado, filas, RESULTADOS_DIR / "reporte_vulnerabilidad.md", algoritmo)
    exportar_hallazgos_csv(mejor_resultado, RESULTADOS_DIR / "hallazgos_detalle.csv")
    exportar_metricas_csv(filas, RESULTADOS_DIR / "metricas_comparativas.csv")

    directorio_graficas = RESULTADOS_DIR / "graficas"
    rutas_graficas = generar_graficas(filas, directorio_graficas)

    print(f"\nReporte completo generado en: {RESULTADOS_DIR / 'reporte_vulnerabilidad.md'}")
    print(f"Metricas (CSV): {RESULTADOS_DIR / 'metricas_comparativas.csv'}")
    print(f"Hallazgos (CSV): {RESULTADOS_DIR / 'hallazgos_detalle.csv'}")
    print("Graficas (SVG): " + ", ".join(str(r) for r in rutas_graficas))


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auditor y Descifrador Concurrente de Contraseñas / Hashes"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    # generate-dataset
    p_gen = sub.add_parser("generate-dataset", help="Genera un dataset sintetico de hashes objetivo")
    p_gen.add_argument("--n", type=int, default=20, help="Numero de hashes objetivo a generar (5-50 recomendado)")
    p_gen.add_argument("--algoritmo", choices=algoritmos_soportados(), default="sha256")
    p_gen.add_argument("--seed", type=int, default=42, help="Semilla para reproducibilidad")
    p_gen.add_argument("--diccionario", default=str(DICCIONARIO_DEFECTO))
    p_gen.add_argument("--salida", default=str(RAIZ / "data" / "hashes_objetivo.csv"))
    p_gen.set_defaults(func=cmd_generate_dataset)

    # audit
    p_audit = sub.add_parser("audit", help="Ejecuta una auditoria (secuencial / hilos / procesos)")
    p_audit.add_argument("--modo", choices=["secuencial", "hilos", "procesos", "paralelo"], default="procesos",
                          help="'paralelo' es un alias retrocompatible de 'procesos'")
    p_audit.add_argument("--workers", type=int, default=4, help="Numero de hilos/procesos (ignorado en modo secuencial)")
    p_audit.add_argument("--algoritmo", choices=algoritmos_soportados(), default="sha256")
    p_audit.add_argument("--objetivos", default=None,
                          help="Archivo CSV o TXT de hashes objetivo (RF-01/RF-07). Si se omite, se genera uno en memoria.")
    p_audit.add_argument("--n", type=int, default=20)
    p_audit.add_argument("--seed", type=int, default=42)
    p_audit.add_argument("--diccionario", default=str(DICCIONARIO_DEFECTO))
    p_audit.add_argument("--batch-size", "--tam-lote-palabras", dest="batch_size", type=int,
                          default=DEFAULT_TAM_LOTE_PALABRAS,
                          help="Palabras base por lote de trabajo (no candidatos: ver docs/ARQUITECTURA.md)")
    p_audit.add_argument("--extendido", action="store_true", help="Motor de mutaciones mas exhaustivo (mas lento)")
    p_audit.set_defaults(func=cmd_audit)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Secuencial vs. hilos vs. procesos (1,2,4,8) + reporte final")
    p_bench.add_argument("--algoritmo", choices=algoritmos_soportados(), default="sha256")
    p_bench.add_argument("--objetivos", default=None)
    p_bench.add_argument("--n", type=int, default=25)
    p_bench.add_argument("--seed", type=int, default=42)
    p_bench.add_argument("--diccionario", default=str(DICCIONARIO_DEFECTO))
    p_bench.add_argument("--batch-size", "--tam-lote-palabras", dest="batch_size", type=int,
                          default=DEFAULT_TAM_LOTE_PALABRAS)
    p_bench.add_argument("--extendido", action="store_true")
    p_bench.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    p_bench.add_argument("--sin-hilos", action="store_true",
                          help="Omite las corridas con threading (solo secuencial + procesos)")
    p_bench.set_defaults(func=cmd_benchmark)

    return parser


def main() -> None:
    parser = construir_parser()
    args = parser.parse_args()
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        args.func(args)
    except Exception as exc:  # pragma: no cover - reporte amigable en CLI
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    mp.freeze_support()
    main()
