"""Pruebas del calculo de metricas de desempeño (RF-11/RF-12)."""

import unittest

from hash_auditor.metrics import construir_tabla_metricas, tabla_como_texto
from hash_auditor.sequential_auditor import Hallazgo, ResultadoAuditoria


def _resultado(modo, num_trabajadores, tiempo_seg, candidatos=1000, descifrados=2, total=2):
    hallazgos = [Hallazgo(f"u{i}", "x", "h" * 8, modo, 0.1) for i in range(descifrados)]
    return ResultadoAuditoria(
        modo=modo, num_trabajadores=num_trabajadores, algoritmo="sha256",
        total_objetivos=total, hallazgos=hallazgos,
        candidatos_evaluados=candidatos, tiempo_total_seg=tiempo_seg,
    )


class TestMetrics(unittest.TestCase):
    def test_requiere_exactamente_un_resultado_secuencial(self):
        with self.assertRaises(ValueError):
            construir_tabla_metricas([_resultado("hilos", 2, 5.0)])  # sin secuencial
        with self.assertRaises(ValueError):
            construir_tabla_metricas([_resultado("secuencial", 1, 10.0), _resultado("secuencial", 1, 9.0)])

    def test_speedup_se_calcula_respecto_al_secuencial(self):
        resultados = [
            _resultado("secuencial", 1, 10.0),
            _resultado("procesos", 2, 5.0),   # 2x mas rapido -> speedup 2.0
            _resultado("procesos", 4, 2.5),   # 4x mas rapido -> speedup 4.0
        ]
        filas = construir_tabla_metricas(resultados)
        por_etiqueta = {f.etiqueta: f for f in filas}

        self.assertAlmostEqual(por_etiqueta["secuencial"].speedup, 1.0)
        self.assertAlmostEqual(por_etiqueta["procesos (N=2)"].speedup, 2.0)
        self.assertAlmostEqual(por_etiqueta["procesos (N=4)"].speedup, 4.0)
        # eficiencia = speedup / N * 100
        self.assertAlmostEqual(por_etiqueta["procesos (N=4)"].eficiencia_pct, 100.0)

    def test_tabla_como_texto_incluye_todas_las_filas(self):
        resultados = [_resultado("secuencial", 1, 10.0), _resultado("hilos", 2, 8.0)]
        filas = construir_tabla_metricas(resultados)
        texto = tabla_como_texto(filas)
        self.assertIn("secuencial", texto)
        self.assertIn("hilos (N=2)", texto)


if __name__ == "__main__":
    unittest.main()
