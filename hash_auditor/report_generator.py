"""
report_generator.py
---------------------
Generacion del reporte estructurado de vulnerabilidades (RF-13):
credenciales recuperadas, trabajador/modo que las encontro, tiempo
individual de hallazgo, y tabla comparativa de rendimiento.

Se exporta en dos formatos sin dependencias externas (RNF-01):
  - Markdown (.md): legible, apto para incluir en el documento tecnico.
  - CSV (.csv): para procesar los hallazgos con otra herramienta si se desea.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import List

from .metrics import FilaMetrica, grafico_ascii_eficiencia, grafico_ascii_speedup, tabla_como_texto
from .sequential_auditor import ResultadoAuditoria


def _nivel_riesgo(fraccion_descifrada: float) -> str:
    if fraccion_descifrada >= 0.75:
        return "CRITICO"
    if fraccion_descifrada >= 0.40:
        return "ALTO"
    if fraccion_descifrada >= 0.10:
        return "MEDIO"
    return "BAJO"


def generar_reporte_markdown(
    resultado_referencia: ResultadoAuditoria,
    filas_metricas: List[FilaMetrica],
    ruta_salida: str | Path,
    algoritmo: str,
) -> str:
    """
    Genera el reporte de vulnerabilidades en Markdown a partir del resultado
    de auditoria mas completo disponible (tipicamente la corrida con mas
    trabajadores, ya que recupera el mayor numero de credenciales) y de la
    tabla comparativa de metricas de todas las configuraciones evaluadas.
    """
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    total = resultado_referencia.total_objetivos
    descifrados = resultado_referencia.descifrados
    fraccion = descifrados / total if total else 0.0
    riesgo = _nivel_riesgo(fraccion)

    lineas = []
    lineas.append("# Reporte de Vulnerabilidad de Contraseñas")
    lineas.append("")
    lineas.append(f"**Fecha de generacion:** {dt.datetime.now().isoformat(timespec='seconds')}")
    lineas.append(f"**Algoritmo de hash auditado:** {algoritmo.upper()}")
    lineas.append(f"**Nivel de riesgo global:** {riesgo}")
    lineas.append("")
    lineas.append("## 1. Resumen Ejecutivo")
    lineas.append("")
    lineas.append(
        f"De un total de **{total}** credenciales objetivo, el sistema logro "
        f"recuperar **{descifrados}** ({fraccion*100:.1f}%) mediante un ataque "
        f"de diccionario hibrido (diccionario base + mutaciones de "
        f"mayusculas/numeros/simbolos)."
    )
    lineas.append("")
    lineas.append(
        "Las credenciales no recuperadas corresponden, en su mayoria, a "
        "contraseñas largas y aleatorias fuera del espacio de busqueda del "
        "diccionario, lo que confirma que la longitud y aleatoriedad reales "
        "siguen siendo la defensa mas efectiva frente a este tipo de ataque."
    )
    lineas.append("")
    lineas.append("## 2. Credenciales Recuperadas")
    lineas.append("")
    if descifrados == 0:
        lineas.append("_No se recupero ninguna credencial en esta corrida._")
    else:
        lineas.append("| # | Usuario | Contraseña recuperada | Hash (prefijo) | Encontrado por | Tiempo (s) |")
        lineas.append("|---|---------|------------------------|-----------------|-----------------|------------|")
        for i, h in enumerate(resultado_referencia.hallazgos, start=1):
            lineas.append(
                f"| {i} | {h.usuario_id} | `{h.password}` | `{h.hash[:12]}...` | "
                f"{h.trabajador} | {h.tiempo_hallazgo_seg:.4f} |"
            )
    lineas.append("")
    lineas.append("## 3. Tabla Comparativa de Rendimiento")
    lineas.append("")
    lineas.append("```")
    lineas.append(tabla_como_texto(filas_metricas))
    lineas.append("```")
    lineas.append("")
    lineas.append("```")
    lineas.append(grafico_ascii_speedup(filas_metricas))
    lineas.append("```")
    lineas.append("")
    lineas.append("```")
    lineas.append(grafico_ascii_eficiencia(filas_metricas))
    lineas.append("```")
    lineas.append("")
    lineas.append("## 4. Recomendaciones de Seguridad")
    lineas.append("")
    lineas.append(
        "- Exigir contraseñas de 14+ caracteres generadas aleatoriamente "
        "(gestor de contraseñas) en lugar de palabras de diccionario con "
        "variaciones predecibles."
    )
    lineas.append("- Aplicar *salting* unico por usuario y funciones de hash "
                   "lentas para credenciales (bcrypt, scrypt o Argon2) en "
                   "lugar de MD5/SHA-256/SHA-512 sin sal.")
    lineas.append("- Forzar autenticacion multifactor (MFA) para reducir el "
                   "impacto de una contraseña comprometida.")
    lineas.append("")

    contenido = "\n".join(lineas)
    ruta_salida.write_text(contenido, encoding="utf-8")
    return contenido


def exportar_hallazgos_csv(resultado: ResultadoAuditoria, ruta_salida: str | Path) -> None:
    """Exporta el detalle de hallazgos a CSV (complementario al Markdown)."""
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with ruta_salida.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["usuario_id", "password", "hash", "trabajador", "tiempo_hallazgo_seg"])
        for h in resultado.hallazgos:
            writer.writerow([h.usuario_id, h.password, h.hash, h.trabajador, f"{h.tiempo_hallazgo_seg:.6f}"])


def exportar_metricas_csv(filas: List[FilaMetrica], ruta_salida: str | Path) -> None:
    """Exporta la tabla comparativa de metricas a CSV."""
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with ruta_salida.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["configuracion", "trabajadores", "tiempo_seg", "descifrados",
                          "total_objetivos", "hashes_evaluados", "throughput_h_s",
                          "speedup", "eficiencia_pct"])
        for fila in filas:
            writer.writerow([
                fila.etiqueta, fila.num_trabajadores, f"{fila.tiempo_seg:.6f}",
                fila.descifrados, fila.total_objetivos, fila.candidatos_evaluados,
                f"{fila.throughput:.2f}", f"{fila.speedup:.4f}", f"{fila.eficiencia_pct:.2f}",
            ])
