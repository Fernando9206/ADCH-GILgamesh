"""Pruebas del generador de graficas SVG (sin dependencias externas)."""

import unittest

from hash_auditor.charts import (
    _color_para_etiqueta,
    grafico_eficiencia_svg,
    grafico_speedup_svg,
    grafico_svg_barras,
    grafico_tiempo_svg,
)


class TestGraficoSvgBarras(unittest.TestCase):
    def test_lanza_error_si_longitudes_no_coinciden(self):
        with self.assertRaises(ValueError):
            grafico_svg_barras(["a", "b"], [1.0], "titulo")

    def test_lista_vacia_no_lanza_zero_division(self):
        # Edge case detectado en docs/ANALISIS_PROYECTO.md: antes
        # `area_ancho / n` lanzaba ZeroDivisionError con listas vacias.
        svg = grafico_svg_barras([], [], "sin datos")
        self.assertIn("<svg", svg)
        self.assertIn("Sin datos", svg)

    def test_svg_valido_contiene_las_etiquetas(self):
        svg = grafico_svg_barras(["secuencial", "procesos (N=4)"], [1.0, 1.8], "Speedup")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("secuencial", svg)
        self.assertIn("procesos (N=4)", svg)
        self.assertIn("</svg>", svg)

    def test_colores_agrupados_por_familia_no_por_indice(self):
        # Dos etiquetas de la MISMA familia deben compartir color, sin
        # importar en que posicion del grafico aparezcan.
        self.assertEqual(_color_para_etiqueta("hilos (N=1)"), _color_para_etiqueta("hilos (N=8)"))
        self.assertEqual(_color_para_etiqueta("procesos (N=2)"), _color_para_etiqueta("procesos (N=4)"))
        # y familias distintas deben usar colores distintos
        self.assertNotEqual(_color_para_etiqueta("hilos (N=1)"), _color_para_etiqueta("procesos (N=1)"))
        self.assertNotEqual(_color_para_etiqueta("secuencial"), _color_para_etiqueta("hilos (N=1)"))


class TestGraficosDeAltoNivelConListaVacia(unittest.TestCase):
    """
    Regresion para el edge case de Revision 3 (docs/ANALISIS_PROYECTO.md):
    `grafico_speedup_svg([])` llamaba `max(...)` sobre un generador vacio
    ANTES de llegar a la guarda de lista vacia de `grafico_svg_barras`,
    lanzando `ValueError: max() arg is an empty sequence`.
    """

    def test_grafico_speedup_svg_con_lista_vacia(self):
        svg = grafico_speedup_svg([])
        self.assertIn("<svg", svg)

    def test_grafico_eficiencia_svg_con_lista_vacia(self):
        svg = grafico_eficiencia_svg([])
        self.assertIn("<svg", svg)

    def test_grafico_tiempo_svg_con_lista_vacia(self):
        svg = grafico_tiempo_svg([])
        self.assertIn("<svg", svg)


if __name__ == "__main__":
    unittest.main()
