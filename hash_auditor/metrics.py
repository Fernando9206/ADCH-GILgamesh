"""
metrics.py
----------
Calculo de metricas de desempeño paralelo (RF-11, RF-12) y utilidades de
presentacion (tabla + grafico ASCII, sin dependencias de terceros, RNF-01).

  Speedup:         S(N)  = T_secuencial / T_paralelo(N)
  Eficiencia:      E(N)  = S(N) / N * 100%
  Throughput:      hashes evaluados / tiempo total  (hashes/seg)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .sequential_auditor import ResultadoAuditoria


@dataclass
class FilaMetrica:
    etiqueta: str                 # "secuencial" o "paralelo (N=4)"
    num_trabajadores: int
    tiempo_seg: float
    candidatos_evaluados: int
    descifrados: int
    total_objetivos: int
    throughput: float             # hashes/seg
    speedup: float                # respecto al secuencial
    eficiencia_pct: float         # speedup / N * 100


def _etiqueta_para(resultado: ResultadoAuditoria) -> str:
    if resultado.modo == "secuencial":
        return "secuencial"
    return f"{resultado.modo} (N={resultado.num_trabajadores})"


def construir_tabla_metricas(resultados: List[ResultadoAuditoria]) -> List[FilaMetrica]:
    """
    Construye la tabla comparativa a partir de una lista de resultados
    heterogenea (p. ej. 1 secuencial + varios de hilos + varios de
    procesos). Debe existir EXACTAMENTE un resultado con `modo="secuencial"`
    dentro de la lista: se usa como linea base para Speedup/Eficiencia de
    todos los demas, sin importar si estos usan hilos o procesos.
    """
    secuenciales = [r for r in resultados if r.modo == "secuencial"]
    if len(secuenciales) != 1:
        raise ValueError(
            "construir_tabla_metricas requiere exactamente un resultado "
            f"con modo='secuencial' (se encontraron {len(secuenciales)})."
        )
    t_sec = secuenciales[0].tiempo_total_seg

    filas: List[FilaMetrica] = []
    for resultado in resultados:
        n = resultado.num_trabajadores
        t = resultado.tiempo_total_seg
        speedup = t_sec / t if t > 0 else float("inf")
        eficiencia = (speedup / n) * 100 if n > 0 else 0.0
        filas.append(
            FilaMetrica(
                etiqueta=_etiqueta_para(resultado),
                num_trabajadores=n,
                tiempo_seg=t,
                candidatos_evaluados=resultado.candidatos_evaluados,
                descifrados=resultado.descifrados,
                total_objetivos=resultado.total_objetivos,
                throughput=resultado.throughput_hashes_seg,
                speedup=speedup,
                eficiencia_pct=eficiencia,
            )
        )

    return filas


def tabla_como_texto(filas: List[FilaMetrica]) -> str:
    """Tabla de metricas formateada como texto plano (para consola/reporte)."""
    encabezados = ["Configuracion", "Tiempo(s)", "Descifrados", "Hashes eval.",
                   "Throughput(h/s)", "Speedup", "Eficiencia(%)"]
    filas_txt = []
    for f in filas:
        filas_txt.append([
            f.etiqueta,
            f"{f.tiempo_seg:.4f}",
            f"{f.descifrados}/{f.total_objetivos}",
            f"{f.candidatos_evaluados:,}",
            f"{f.throughput:,.1f}",
            f"{f.speedup:.2f}x",
            f"{f.eficiencia_pct:.1f}%",
        ])

    anchos = [len(h) for h in encabezados]
    for fila in filas_txt:
        for i, celda in enumerate(fila):
            anchos[i] = max(anchos[i], len(celda))

    def formatear_fila(celdas):
        return " | ".join(c.ljust(anchos[i]) for i, c in enumerate(celdas))

    separador = "-+-".join("-" * a for a in anchos)
    lineas = [formatear_fila(encabezados), separador]
    lineas += [formatear_fila(f) for f in filas_txt]
    return "\n".join(lineas)


def grafico_ascii_speedup(filas: List[FilaMetrica], ancho_max: int = 50) -> str:
    """
    Grafico de barras ASCII del Speedup por configuracion, sin dependencias
    externas (matplotlib, etc. quedan fuera por RNF-01).
    """
    if not filas:
        return ""
    max_speedup = max(f.speedup for f in filas) or 1.0
    lineas = ["Speedup relativo (T_secuencial / T_paralelo):", ""]
    for f in filas:
        longitud = max(1, round((f.speedup / max_speedup) * ancho_max))
        barra = "#" * longitud
        lineas.append(f"{f.etiqueta:<16} | {barra} {f.speedup:.2f}x")
    return "\n".join(lineas)


def grafico_ascii_eficiencia(filas: List[FilaMetrica], ancho_max: int = 50) -> str:
    """Grafico de barras ASCII de la eficiencia paralela (%) por configuracion."""
    if not filas:
        return ""
    lineas = ["Eficiencia paralela (Speedup / N_trabajadores):", ""]
    for f in filas:
        longitud = max(1, round(min(f.eficiencia_pct, 100.0) / 100 * ancho_max))
        barra = "#" * longitud
        lineas.append(f"{f.etiqueta:<16} | {barra} {f.eficiencia_pct:.1f}%")
    return "\n".join(lineas)
