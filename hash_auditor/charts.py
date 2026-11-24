"""
charts.py
---------
Generador de graficas vectoriales (SVG) para el documento tecnico y la
presentacion, construido a mano con cadenas de texto -- sin ninguna
dependencia de terceros (RNF-01: ni matplotlib ni similares). SVG es XML
plano, por lo que no hace falta mas que `string` y `pathlib` de la
biblioteca estandar.

Un archivo `.svg` se abre directamente en cualquier navegador o se puede
insertar como imagen en Word/Google Docs/LaTeX para el informe PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from .metrics import FilaMetrica

_PALETA = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2"]

# Color fijo por FAMILIA de motor en vez de rotar por indice (0,1,2,3...):
# con 9 barras tipicas (secuencial + 4 de hilos + 4 de procesos), rotar por
# indice sobre una paleta de 6 colores mezclaba visualmente las series
# (p. ej. "hilos (N=4)" y "procesos (N=2)" podian terminar del mismo color
# por pura coincidencia modular). Agrupar por familia hace que todas las
# barras de "hilos" compartan un color y todas las de "procesos" otro,
# facilitando la lectura del grafico en el informe/presentacion.
_COLOR_SECUENCIAL = "#9CA3AF"   # gris: la linea base, sin paralelismo
_COLOR_HILOS = "#F58518"        # naranja: threading (limitado por el GIL)
_COLOR_PROCESOS = "#4C78A8"     # azul: multiprocessing (paralelismo real)


def _color_para_etiqueta(etiqueta: str) -> str:
    etiqueta = etiqueta.lower()
    if etiqueta.startswith("secuencial"):
        return _COLOR_SECUENCIAL
    if etiqueta.startswith("hilos"):
        return _COLOR_HILOS
    if etiqueta.startswith("procesos") or etiqueta.startswith("paralelo"):
        return _COLOR_PROCESOS
    return _PALETA[0]  # motor desconocido/futuro: color por defecto


def _escapar_xml(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def grafico_svg_barras(
    etiquetas: Sequence[str],
    valores: Sequence[float],
    titulo: str,
    sufijo_valor: str = "",
    linea_referencia: float | None = None,
    etiqueta_referencia: str = "ideal",
    ancho: int = 760,
    alto: int = 420,
) -> str:
    """
    Construye un grafico de barras verticales en SVG puro.

    `linea_referencia` (opcional) dibuja una linea punteada horizontal,
    util para marcar el Speedup "ideal" (= numero de trabajadores) y
    contrastarlo visualmente contra el Speedup real obtenido.
    """
    if len(etiquetas) != len(valores):
        raise ValueError("etiquetas y valores deben tener la misma longitud")

    if not etiquetas:
        # Sin datos que graficar (p. ej. un benchmark con --workers vacio):
        # se devuelve un SVG valido con un aviso en vez de lanzar
        # ZeroDivisionError al calcular `area_ancho / n` mas abajo.
        return (
            f'<svg viewBox="0 0 {ancho} {alto}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Segoe UI, Arial, sans-serif">'
            f'<rect x="0" y="0" width="{ancho}" height="{alto}" fill="#ffffff"/>'
            f'<text x="{ancho/2}" y="{alto/2}" text-anchor="middle" font-size="16" '
            f'fill="#6b7280">Sin datos para "{_escapar_xml(titulo)}"</text>'
            f'</svg>'
        )

    margen_izq, margen_der, margen_sup, margen_inf = 70, 30, 60, 90
    area_ancho = ancho - margen_izq - margen_der
    area_alto = alto - margen_sup - margen_inf

    valor_max = max([*valores, linea_referencia or 0, 1e-9])
    valor_max *= 1.15  # un poco de aire arriba de la barra mas alta

    n = len(valores)
    ancho_barra = area_ancho / n * 0.6
    espacio = area_ancho / n

    partes: List[str] = []
    partes.append(
        f'<svg viewBox="0 0 {ancho} {alto}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="Segoe UI, Arial, sans-serif">'
    )
    partes.append(f'<rect x="0" y="0" width="{ancho}" height="{alto}" fill="#ffffff"/>')
    partes.append(
        f'<text x="{ancho/2}" y="28" text-anchor="middle" font-size="20" '
        f'font-weight="bold" fill="#1f2a37">{_escapar_xml(titulo)}</text>'
    )

    # Eje Y + lineas de referencia (grid)
    num_divisiones = 5
    for i in range(num_divisiones + 1):
        valor_y = valor_max * i / num_divisiones
        y = margen_sup + area_alto - (valor_y / valor_max) * area_alto
        partes.append(
            f'<line x1="{margen_izq}" y1="{y:.1f}" x2="{ancho - margen_der}" y2="{y:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{margen_izq - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="12" fill="#6b7280">{valor_y:,.1f}</text>'
        )

    # Linea de referencia ("ideal")
    if linea_referencia is not None:
        y_ref = margen_sup + area_alto - (linea_referencia / valor_max) * area_alto
        partes.append(
            f'<line x1="{margen_izq}" y1="{y_ref:.1f}" x2="{ancho - margen_der}" y2="{y_ref:.1f}" '
            f'stroke="#9ca3af" stroke-width="2" stroke-dasharray="6,4"/>'
        )
        partes.append(
            f'<text x="{ancho - margen_der}" y="{y_ref - 6:.1f}" text-anchor="end" '
            f'font-size="12" fill="#6b7280">{_escapar_xml(etiqueta_referencia)}</text>'
        )

    # Barras
    for i, (etiqueta, valor) in enumerate(zip(etiquetas, valores)):
        x = margen_izq + i * espacio + (espacio - ancho_barra) / 2
        alto_barra = (valor / valor_max) * area_alto if valor_max else 0
        y = margen_sup + area_alto - alto_barra
        color = _color_para_etiqueta(etiqueta)
        partes.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{ancho_barra:.1f}" height="{alto_barra:.1f}" '
            f'fill="{color}" rx="3"/>'
        )
        partes.append(
            f'<text x="{x + ancho_barra/2:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
            f'font-size="13" font-weight="bold" fill="#1f2a37">{valor:,.2f}{sufijo_valor}</text>'
        )
        # Etiqueta del eje X (rotada si son muchas barras)
        texto_x = x + ancho_barra / 2
        texto_y = margen_sup + area_alto + 20
        partes.append(
            f'<text x="{texto_x:.1f}" y="{texto_y:.1f}" text-anchor="end" '
            f'font-size="12" fill="#374151" transform="rotate(-30 {texto_x:.1f} {texto_y:.1f})">'
            f'{_escapar_xml(etiqueta)}</text>'
        )

    # Eje
    partes.append(
        f'<line x1="{margen_izq}" y1="{margen_sup + area_alto}" '
        f'x2="{ancho - margen_der}" y2="{margen_sup + area_alto}" stroke="#374151" stroke-width="1.5"/>'
    )
    partes.append("</svg>")
    return "\n".join(partes)


def grafico_speedup_svg(filas: List[FilaMetrica]) -> str:
    etiquetas = [f.etiqueta for f in filas]
    valores = [f.speedup for f in filas]
    # `default=1` evita `ValueError: max() arg is an empty sequence` si
    # `filas` llega vacio (p. ej. un benchmark con --workers sin valores):
    # el caso vacio en si lo maneja `grafico_svg_barras`, pero este max()
    # se evalua ANTES de llegar a esa guarda (docs/ANALISIS_PROYECTO.md).
    max_n = max((f.num_trabajadores for f in filas), default=1) or 1
    return grafico_svg_barras(
        etiquetas, valores,
        titulo="Speedup (T_secuencial / T_configuracion)",
        sufijo_valor="x",
        linea_referencia=float(max_n),
        etiqueta_referencia=f"ideal (N={max_n})",
    )


def grafico_eficiencia_svg(filas: List[FilaMetrica]) -> str:
    etiquetas = [f.etiqueta for f in filas]
    valores = [f.eficiencia_pct for f in filas]
    return grafico_svg_barras(
        etiquetas, valores,
        titulo="Eficiencia paralela (Speedup / N_trabajadores x 100%)",
        sufijo_valor="%",
        linea_referencia=100.0,
        etiqueta_referencia="ideal (100%)",
    )


def grafico_tiempo_svg(filas: List[FilaMetrica]) -> str:
    etiquetas = [f.etiqueta for f in filas]
    valores = [f.tiempo_seg for f in filas]
    return grafico_svg_barras(
        etiquetas, valores,
        titulo="Tiempo total de ejecucion (segundos)",
        sufijo_valor="s",
    )


def guardar_svg(contenido: str, ruta: str | Path) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def generar_graficas(filas: List[FilaMetrica], directorio_salida: str | Path) -> List[Path]:
    """Genera las 3 graficas estandar (Speedup, Eficiencia, Tiempo) y las guarda como .svg."""
    directorio_salida = Path(directorio_salida)
    rutas = []
    generadores = {
        "grafico_speedup.svg": grafico_speedup_svg,
        "grafico_eficiencia.svg": grafico_eficiencia_svg,
        "grafico_tiempo.svg": grafico_tiempo_svg,
    }
    for nombre, generador in generadores.items():
        ruta = directorio_salida / nombre
        guardar_svg(generador(filas), ruta)
        rutas.append(ruta)
    return rutas
