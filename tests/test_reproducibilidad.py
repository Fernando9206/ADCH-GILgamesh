"""Pruebas de reproducibilidad del generador de datasets sinteticos (RF-02)."""

import unittest
from pathlib import Path

from hash_auditor.dataset_generator import generar_dataset

DICCIONARIO = Path(__file__).resolve().parent.parent / "data" / "diccionario_base.txt"


class TestReproducibilidad(unittest.TestCase):
    def test_misma_semilla_produce_el_mismo_dataset(self):
        objetivos_1, referencia_1 = generar_dataset(15, "sha256", DICCIONARIO, seed=123)
        objetivos_2, referencia_2 = generar_dataset(15, "sha256", DICCIONARIO, seed=123)
        self.assertEqual(objetivos_1, objetivos_2)
        self.assertEqual(referencia_1, referencia_2)

    def test_semillas_distintas_producen_datasets_distintos(self):
        objetivos_1, _ = generar_dataset(15, "sha256", DICCIONARIO, seed=1)
        objetivos_2, _ = generar_dataset(15, "sha256", DICCIONARIO, seed=2)
        self.assertNotEqual(objetivos_1, objetivos_2)

    def test_hashes_coinciden_con_las_contrasenas_de_referencia(self):
        from hash_auditor.hash_engine import calcular_hash

        objetivos, referencia = generar_dataset(10, "sha256", DICCIONARIO, seed=7)
        referencia_por_usuario = {r.usuario_id: r.password for r in referencia}
        for obj in objetivos:
            password_real = referencia_por_usuario[obj.usuario_id]
            self.assertEqual(obj.hash, calcular_hash(password_real, "sha256"))

    def test_n_registros_generados(self):
        objetivos, referencia = generar_dataset(12, "md5", DICCIONARIO, seed=5)
        self.assertEqual(len(objetivos), 12)
        self.assertEqual(len(referencia), 12)


if __name__ == "__main__":
    unittest.main()
