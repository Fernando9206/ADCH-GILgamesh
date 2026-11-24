"""Pruebas del diccionario base y el motor de mutaciones (RF-03)."""

import unittest

from hash_auditor.dictionary import (
    estimar_total_candidatos,
    generar_candidatos,
    generar_lotes,
    generar_lotes_palabras,
    mutar_palabra,
)


class TestMotorMutaciones(unittest.TestCase):
    def test_mutar_palabra_incluye_la_palabra_original(self):
        variantes = list(mutar_palabra("dragon", incluir_extendido=False))
        self.assertIn("dragon", variantes)
        self.assertIn("Dragon", variantes)
        self.assertIn("DRAGON", variantes)

    def test_mutar_palabra_incluye_sufijos_y_simbolos(self):
        variantes = list(mutar_palabra("test", incluir_extendido=False))
        self.assertIn("test123", variantes)
        self.assertIn("test!", variantes)
        self.assertIn("test123!", variantes)

    def test_estimar_total_candidatos_coincide_con_el_conteo_real(self):
        palabras = ["dragon", "shadow", "ninja"]
        estimado = estimar_total_candidatos(len(palabras), incluir_extendido=False)
        reales = len(list(generar_candidatos(palabras, incluir_extendido=False)))
        self.assertEqual(estimado, reales)

    def test_modo_extendido_genera_mas_candidatos_que_el_normal(self):
        palabras = ["dragon"]
        normal = estimar_total_candidatos(len(palabras), incluir_extendido=False)
        extendido = estimar_total_candidatos(len(palabras), incluir_extendido=True)
        self.assertGreater(extendido, normal)

    def test_generar_lotes_no_pierde_ni_duplica_candidatos(self):
        palabras = ["ninja", "dragon"]
        esperados = list(generar_candidatos(palabras, incluir_extendido=False))
        obtenidos = []
        for lote in generar_lotes(palabras, batch_size=37, incluir_extendido=False):
            obtenidos.extend(lote)
        self.assertEqual(esperados, obtenidos)

    def test_generar_lotes_palabras_particiona_sin_perdidas(self):
        palabras = [f"palabra{i}" for i in range(23)]
        vistas = []
        for lote in generar_lotes_palabras(palabras, tam_lote=4):
            self.assertLessEqual(len(lote), 4)
            vistas.extend(lote)
        self.assertEqual(sorted(vistas), sorted(palabras))
        # ninguna palabra debe repetirse entre lotes (particion disjunta)
        self.assertEqual(len(vistas), len(set(vistas)))


if __name__ == "__main__":
    unittest.main()
